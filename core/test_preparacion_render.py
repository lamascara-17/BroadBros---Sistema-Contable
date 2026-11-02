"""Regresiones de la auditoría final; nunca utilizan una base de producción."""
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from django.db import close_old_connections, transaction
from django.test import TransactionTestCase, SimpleTestCase, override_settings
from django.urls import reverse
from .contexto_bot import firma_caso, conversacion_caso, guardar_conversacion
from .models import Workspace, AsientoContable, Movimiento, CuentaContable
from .respaldo_stream import validar_archivo
from .test_respaldos_recursos import Visitantes
from .test_estados_financieros import novatech
from .views import guardar_importacion, escribir_asiento
from .workspaces import actual


@override_settings(WORKSPACE_ISOLATION=True)
class PreparacionRenderTests(Visitantes, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.sembrar(self.a)
        self.token = actual.set(self.a.session['workspace_id'])
        self.addCleanup(actual.reset, self.token)

    def test_revision_cubre_edicion_glosa_importe_catalogo_bulk_y_borrado(self):
        firma = firma_caso()
        asiento = AsientoContable.objects.first()
        operaciones = [
            lambda: AsientoContable.objects.filter(pk=asiento.pk).update(descripcion='Glosa editada'),
            lambda: Movimiento.objects.filter(asiento=asiento).update(monto=30100),
            lambda: CuentaContable.objects.filter(codigo='50').update(nombre='Capital aportado'),
            lambda: Movimiento.objects.filter(asiento=asiento).delete(),
            lambda: AsientoContable.objects.filter(pk=asiento.pk).delete(),
        ]
        for operacion in operaciones:
            operacion()
            nueva = firma_caso()
            self.assertGreater(nueva['revision'], firma['revision'])
            firma = nueva

    def test_rollback_restaura_version_y_conversacion(self):
        firma = firma_caso()
        turnos = [{'usuario':'Caja', 'respuesta':'Saldo del caso'}]
        self.assertTrue(guardar_conversacion(firma, 0, turnos))
        with self.assertRaises(ValueError):
            with transaction.atomic():
                AsientoContable.objects.all().update(descripcion='Cambio que falla')
                self.assertNotEqual(firma_caso(), firma)
                raise ValueError('Fallo deliberado')
        self.assertEqual(firma_caso(), firma)
        self.assertEqual(conversacion_caso({}, firma)[0], turnos)

    def test_edicion_confirmada_y_regreso_al_valor_inicial_no_reutiliza_version(self):
        firma = firma_caso()
        asiento = AsientoContable.objects.first()
        original = asiento.descripcion
        asiento.descripcion = 'Otra glosa'; asiento.save()
        asiento.descripcion = original; asiento.save()
        self.assertGreater(firma_caso()['revision'], firma['revision'])

    def test_dos_respuestas_simultaneas_solo_una_confirma(self):
        firma = firma_caso()
        workspace = actual.get()
        barrera = Barrier(2)
        def responder(i):
            close_old_connections()
            token = actual.set(workspace)
            try:
                _, secuencia = conversacion_caso({}, firma)
                barrera.wait(timeout=10)
                return guardar_conversacion(firma, secuencia, [{'usuario':str(i),'respuesta':'Válida'}])
            finally:
                actual.reset(token)
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(responder, range(2)))
        self.assertEqual(sorted(resultados), [False, True])
        self.assertEqual(Workspace.objects.get(pk=workspace).bot_sequence, 1)

    def test_cambio_durante_llamada_ia_devuelve_409_y_no_guarda_respuesta_vieja(self):
        def respuesta(*args, **kwargs):
            AsientoContable.objects.all().update(descripcion='Caso cambiado durante la consulta')
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Respuesta anterior'))])
        with override_settings(GROQ_API_KEY='clave-ficticia'), patch('core.views.consulta_contable', return_value=True), patch('core.views.Groq') as groq:
            groq.return_value.chat.completions.create.side_effect = respuesta
            r = self.a.post(reverse('chatbot_api'), {'message':'Explica el saldo de caja'})
        self.assertEqual(r.status_code,409)
        self.assertNotIn('Respuesta anterior',str(Workspace.objects.get(pk=actual.get()).bot_turnos))

    def test_version_y_conversacion_independientes_entre_visitantes(self):
        firma_a = firma_caso()
        token = actual.set(self.b.session['workspace_id'])
        try:
            firma_b = firma_caso()
            guardar_importacion(novatech()[:1])
            self.assertNotEqual(firma_caso(), firma_b)
            self.assertFalse(guardar_conversacion(firma_a, 0, []))
        finally: actual.reset(token)
        self.assertEqual(firma_caso(), firma_a)

    def test_limite_manual_es_el_del_respaldo_y_edicion_sigue_permitida(self):
        asiento = AsientoContable.objects.first()
        with patch('core.respaldos.MAX_ASIENTOS_RESPALDO', AsientoContable.objects.count()):
            with self.assertRaisesMessage(ValueError, '1 000 asientos'):
                escribir_asiento({}, {})
        self.assertEqual(AsientoContable.objects.count(),7)

    def test_jsonb_no_cambia_huella_portable_por_orden_de_claves(self):
        from .respaldos import serializar_caso
        from .respaldo_stream import archivo_historico, archivo_actual
        from .models import RespaldoCaso
        def invertir(valor):
            if isinstance(valor, dict):return {k:invertir(v) for k,v in reversed(list(valor.items()))}
            if isinstance(valor, list):return [invertir(v) for v in valor]
            return valor
        contenido = invertir(serializar_caso())
        respaldo = RespaldoCaso.objects.create(datos=contenido['asientos'],catalogo=contenido['cuentas'])
        with archivo_historico(respaldo) as historico, archivo_actual() as vigente:
            self.assertEqual(historico.read(),vigente.read())

    def test_parser_rechaza_profundo_campo_gigante_duplicado_y_listas_no_acotadas(self):
        casos = [b'{"asientos":[],"cuentas":[{"nombre":"'+b'a'*201+b'"}]}',
            b'{"asientos":[],"cuentas":[{"fuente":"dato fuera de lugar"}]}',
            b'[' * 13 + b'0' + b']' * 13,
            b'{"asientos":[],"cuentas":[],"version":1,"version":1}',
            b'{"asientos":[],"cuentas":[],"formato":"'+b'a'*200001+b'"}',
            b'{"asientos":[],"cuentas":[[]]}',
            b'{"asientos":[],"cuentas":[],"version":NaN}',
            b'{"asientos":[],"cuentas":[],"version":1.0}',
            b'{"asientos":[],"cuentas":[]} trailing']
        for contenido in casos:
            with self.subTest(tamano=len(contenido)), self.assertRaises(ValueError):
                validar_archivo(BytesIO(contenido))

    def test_ratios_intereses_y_da_no_se_anulan_al_cerrar_resultados(self):
        interes = CuentaContable.objects.create(codigo='673',nombre='Intereses de préstamos',tipo='gasto',subcategoria='gasto_financiero')
        da = CuentaContable.objects.create(codigo='681',nombre='Depreciación',tipo='gasto',subcategoria='gasto_operativo')
        caja = CuentaContable.objects.get(codigo='101')
        for cuenta, monto in ((interes,100),(da,200)):
            a = AsientoContable.objects.create(fecha='2025-10-30',descripcion=cuenta.nombre)
            Movimiento.objects.bulk_create([Movimiento(asiento=a,cuenta=cuenta,tipo='debe',monto=monto),
                Movimiento(asiento=a,cuenta=caja,tipo='haber',monto=monto)])
        from .ratios_caso import calcular_caso
        antes = calcular_caso()['resultado']
        self.assertEqual(antes['ebitda'],11000)
        cierre = AsientoContable.objects.create(fecha='2025-10-31',descripcion='Cierre',clase='cierre')
        patrimonio = CuentaContable.objects.create(codigo='59',nombre='Resultados acumulados',tipo='patrimonio')
        Movimiento.objects.bulk_create([Movimiento(asiento=cierre,cuenta=CuentaContable.objects.get(codigo='704'),tipo='debe',monto=15000),
            Movimiento(asiento=cierre,cuenta=CuentaContable.objects.get(codigo='63'),tipo='haber',monto=4000),
            Movimiento(asiento=cierre,cuenta=interes,tipo='haber',monto=100),
            Movimiento(asiento=cierre,cuenta=da,tipo='haber',monto=200),
            Movimiento(asiento=cierre,cuenta=patrimonio,tipo='haber',monto=10700)])
        despues = calcular_caso()['resultado']
        for clave in ('interest_cover','ebitda_margin','net_margin'):
            self.assertEqual(despues['values'][clave],antes['values'][clave])
        self.assertEqual(despues['ebitda'],11000)


class ConfiguracionEntornoTests(SimpleTestCase):
    def test_database_url_vacia_utiliza_sqlite_configurada(self):
        import os
        import subprocess
        import sys
        entorno = os.environ.copy()
        entorno.update(DATABASE_URL='', SQLITE_PATH='/tmp/broadbros-config-only.sqlite3',
            SECRET_KEY='solo-comprobacion-sin-conexion-a-bd', DJANGO_SETTINGS_MODULE='contabilidad.settings', RENDER='false')
        salida = subprocess.check_output([sys.executable, '-c',
            'from django.conf import settings; print(settings.DATABASES["default"]["ENGINE"])'],env=entorno,text=True)
        self.assertEqual(salida.strip(), 'django.db.backends.sqlite3')
