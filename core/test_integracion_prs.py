"""Regresiones de integración entre las auditorías #6 y #7."""
from unittest.mock import patch
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from .models import AsientoContable, CuentaContable, Movimiento, RespaldoCaso
from .ratios_caso import calcular_caso
from .test_estados_financieros import novatech
from .test_respaldos_recursos import Visitantes
from .workspaces import actual


@override_settings(WORKSPACE_ISOLATION=True)
class IntegracionAuditoriasTests(Visitantes, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.sembrar(self.a)
        self.token = actual.set(self.a.session['workspace_id'])
        self.addCleanup(actual.reset, self.token)

    def test_importar_el_mismo_caso_no_duplica_sus_copias_recuperables(self):
        archivo = self.exportar(self.a).content
        for _ in range(2):
            self.assertEqual(self.subir(self.a, archivo).status_code, 302)
        self.assertEqual(RespaldoCaso.objects.count(), 1)
        self.assertEqual(self.exportar(self.a).content, archivo)

    def test_da_analitica_no_duplica_ebitda_ni_cobertura(self):
        caja = CuentaContable.objects.get(codigo='101')
        interes = CuentaContable.objects.create(codigo='673', nombre='Intereses', tipo='gasto', subcategoria='gasto_financiero')
        da = CuentaContable.objects.create(codigo='681', nombre='Depreciación', tipo='gasto', subcategoria='gasto_operativo')
        for cuenta, importe in ((interes, 100), (da, 200)):
            a = AsientoContable.objects.create(fecha='2025-10-30', descripcion=cuenta.nombre)
            Movimiento.objects.bulk_create([Movimiento(asiento=a, cuenta=cuenta, tipo='debe', monto=importe),
                Movimiento(asiento=a, cuenta=caja, tipo='haber', monto=importe)])
        antes = calcular_caso()['resultado']
        destino = CuentaContable.objects.create(codigo='94', nombre='Depreciación por destino', tipo='gasto', subcategoria='gasto_operativo')
        contrapartida = CuentaContable.objects.create(codigo='79', nombre='Cargas imputables', tipo='ingreso')
        a = AsientoContable.objects.create(fecha='2025-10-30', descripcion='Destino analítico')
        Movimiento.objects.bulk_create([Movimiento(asiento=a, cuenta=destino, tipo='debe', monto=200),
            Movimiento(asiento=a, cuenta=contrapartida, tipo='haber', monto=200)])
        despues = calcular_caso()['resultado']
        self.assertEqual(despues['ebitda'], antes['ebitda'])
        for clave in ('ebitda_margin', 'interest_cover', 'operating_margin', 'net_margin'):
            self.assertEqual(despues['values'][clave], antes['values'][clave])

    def test_calculo_determinista_tardio_no_devuelve_un_saldo_anterior(self):
        def calcular(mensaje):
            AsientoContable.objects.all().update(descripcion='Cambio confirmado durante el cálculo')
            return 'SALDO_ANTERIOR_NO_PUBLICAR'
        with patch('core.bot_calculos.respuesta_calculada', side_effect=calcular):
            respuesta = self.a.post(reverse('chatbot_api'), {'message':'Cuál es el saldo de caja'})
        self.assertEqual(respuesta.status_code, 409)
        self.assertNotIn('SALDO_ANTERIOR_NO_PUBLICAR', respuesta.content.decode())

    def test_apertura_historica_usa_la_misma_clasificacion_que_los_estados(self):
        AsientoContable.objects.order_by('fecha','pk').filter(descripcion='Aporte inicial').update(
            descripcion='Por los saldos de apertura del ejercicio')
        calculo = calcular_caso()
        self.assertTrue(calculo['contexto']['apertura_documentada'])
        self.assertIsNotNone(calculo['resultado']['values']['roe'])

    def test_importaciones_distintas_conservan_ambas_versiones_y_aislamiento(self):
        self.sembrar(self.b, novatech()[:1])
        nuevo = self.exportar(self.b).content
        viejo = self.exportar(self.a).content
        self.subir(self.a, nuevo)
        self.assertEqual(RespaldoCaso.objects.count(), 2)
        for respaldo in RespaldoCaso.objects.all():
            self.assertEqual(self.b.get(reverse('descargar_respaldo', args=[respaldo.pk])).status_code, 404)
        for _ in range(2): self.subir(self.a, nuevo)
        self.assertEqual(RespaldoCaso.objects.count(), 2)
        self.assertEqual(self.exportar(self.a).content, nuevo)
        from .respaldo_stream import archivo_historico
        copias=[]
        for respaldo in RespaldoCaso.objects.all():
            with archivo_historico(respaldo) as f: copias.append(f.read())
        self.assertIn(viejo, copias)
        self.assertIn(nuevo, copias)

    def test_fallo_guardando_importado_revierte_caso_y_copias(self):
        viejo = self.exportar(self.a).content
        sesion = self.a.session
        sesion['nonobot_turnos'] = [{'usuario':'Pregunta anterior','respuesta':'Contexto conservado'}]
        sesion.save()
        self.sembrar(self.b, novatech()[:1])
        nuevo = self.exportar(self.b).content
        from .respaldo_stream import guardar_archivo
        llamadas = []
        def conservar(archivo):
            llamadas.append(True)
            if len(llamadas) == 2: raise ValueError('Fallo después de restaurar')
            return guardar_archivo(archivo)
        with patch('core.respaldo_stream.guardar_archivo', side_effect=conservar):
            self.subir(self.a, nuevo)
        self.assertEqual(len(llamadas), 2)
        self.assertEqual(self.exportar(self.a).content, viejo)
        self.assertEqual(RespaldoCaso.objects.count(), 0)
        self.assertEqual(self.a.session['nonobot_turnos'], [{'usuario':'Pregunta anterior','respuesta':'Contexto conservado'}])

    def test_calculo_tras_rollback_no_produce_409_innecesario(self):
        def calcular(mensaje):
            try:
                with transaction.atomic():
                    AsientoContable.objects.all().update(descripcion='Cambio revertido')
                    raise ValueError('Rollback deliberado')
            except ValueError: pass
            return 'Resultado vigente'
        with patch('core.bot_calculos.respuesta_calculada', side_effect=calcular):
            r = self.a.post(reverse('chatbot_api'), {'message':'Cuál es la utilidad'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['response'], 'Resultado vigente')

    def test_copia_por_bloques_identica_reutiliza_fragmentos(self):
        from tempfile import TemporaryFile
        from .respaldos import serializar_caso
        from .respaldo_stream import escribir_caso, guardar_archivo
        from .models import RespaldoFragmento
        contenido = serializar_caso()
        asiento = {**contenido['asientos'][0], 'fuente':'x'*20000}
        with TemporaryFile('w+b') as f:
            escribir_caso(f, [asiento]*30, contenido['cuentas'])
            primero = guardar_archivo(f)
            bloques = RespaldoFragmento.objects.filter(respaldo=primero).count()
            segundo = guardar_archivo(f)
        self.assertGreater(bloques, 0)
        self.assertEqual(primero.pk, segundo.pk)
        self.assertEqual(RespaldoFragmento.objects.filter(respaldo=primero).count(), bloques)

    def test_17_ratios_del_caso_coinciden_entre_pantalla_y_csv(self):
        import csv
        from io import StringIO
        from .ratio_views import safe_csv
        ruta = reverse('ratios_caso')
        pantalla = self.a.get(ruta)
        exportado = self.a.get(ruta+'?descargar=csv')
        filas = list(csv.reader(StringIO(exportado.content.decode('utf-8-sig'))))[2:]
        self.assertEqual(len(filas), 17)
        for visible, fila in zip(pantalla.context['filas'], filas):
            self.assertEqual(fila, [safe_csv(visible[k]) for k in ('nombre','formula','valor','motivo')])

    def test_17_ratios_comparativos_coinciden_entre_pantalla_y_csv(self):
        import csv
        from io import StringIO
        from .ratio_views import safe_csv
        ruta = reverse('ratios_financieros')
        pantalla = self.a.get(ruta)
        exportado = self.a.get(ruta+'?descargar=csv')
        filas = list(csv.reader(StringIO(exportado.content.decode('utf-8-sig'))))[3:20]
        self.assertEqual(len(filas), 17)
        for visible, fila in zip(pantalla.context['rows'], filas):
            self.assertEqual(fila, [safe_csv(visible[k]) for k in ('label','unit','previous','own','leader','sector','n','formula','reason')])

    def test_copias_identicas_de_visitantes_distintos_no_comparten_respaldo(self):
        archivo = self.exportar(self.a).content
        self.subir(self.a, archivo)
        copia_a = RespaldoCaso.objects.get()
        self.subir(self.b, archivo)
        token = actual.set(self.b.session['workspace_id'])
        try: copia_b = RespaldoCaso.objects.get()
        finally: actual.reset(token)
        self.assertNotEqual(copia_a.pk, copia_b.pk)
        self.assertEqual(self.a.get(reverse('descargar_respaldo', args=[copia_b.pk])).status_code,404)
        self.assertEqual(self.b.get(reverse('descargar_respaldo', args=[copia_a.pk])).status_code,404)
