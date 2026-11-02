import csv
import json
from copy import deepcopy
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core.cache import cache
from openpyxl import load_workbook
from pypdf import PdfReader
from .models import CuentaContable, AsientoContable, Movimiento, RespaldoCaso
from .test_estados_financieros import novatech
from .views import guardar_importacion
from .reporte_utils import contexto_estados
from .validacion_contable import auditar_asientos, validar_cuenta
from .workspaces import actual


class AuditoriaContableTests(TestCase):
    def test_novatech_seis_operaciones_y_siete_reportes(self):
        # El caso A solicitado tiene seis operaciones, no incluye servicios básicos.
        guardar_importacion(novatech()[:6])
        c = contexto_estados()
        self.assertEqual(len(c['asientos']), 6)
        for clave, esperado in {'gran_total_debe':67000, 'gran_total_haber':67000,
            'total_activos':45000, 'total_pasivos':3000, 'total_patrimonio_con_resultados':42000,
            'resultado_neto':12000}.items(): self.assertEqual(c[clave], esperado)
        self.assertEqual(c['mayor_datos'][0]['saldo_final'], 30000)
        xlsx = self.client.post(reverse('reporte_completo'), {'formato':'excel', 'empresa':'NovaTech & Diseño'})
        libro = load_workbook(BytesIO(xlsx.content), data_only=True)
        self.assertEqual(len(libro.sheetnames), 7)
        self.assertEqual(libro['Situación Financiera']['A1'].value, 'NovaTech & Diseño')
        self.assertTrue(any(row[0] == 'TOTAL PATRIMONIO' and row[4] == 42000 for row in libro['Cambios en el Patrimonio'].iter_rows(values_only=True)))
        pdf = self.client.post(reverse('reporte_completo'), {'formato':'pdf', 'empresa':'NovaTech & Diseño'})
        paginas = PdfReader(BytesIO(pdf.content)).pages
        texto = '\n'.join(p.extract_text() for p in paginas)
        for titulo in ('Estado de Cambios en el Patrimonio','Estado de Flujos de Efectivo','Libro Diario','Libro Mayor','Balance de Comprobación'):
            self.assertIn(titulo, texto)
        self.assertGreaterEqual(len(paginas), 7)
        for ruta in ('estado_patrimonio', 'estado_flujos'):
            self.assertEqual(self.client.get(reverse(ruta)).status_code, 200)

    def test_reproduccion_12_asientos_2009_detecta_ajuste_incorrecto(self):
        datos = json.loads((Path(__file__).parent/'testdata/auditoria_2009.json').read_text())
        self.assertEqual(len(datos),12)
        notas = auditar_asientos(datos)
        self.assertTrue(any('2,500.00' in n and '500.00' in n for n in notas))
        self.assertTrue(any('capital' in n.lower() for n in notas))
        mov = datos[-1]['movimientos']
        self.assertTrue(any(Decimal(m['monto']) == 5400 for m in mov))
        self.assertEqual(Decimal('5900')-Decimal('2500'), Decimal('3400'))
        with self.assertRaises(ValueError): guardar_importacion(datos)
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_codigo_y_naturaleza_no_aceptan_catalogo_incompatible(self):
        for codigo,nombre,tipo in [('1101','Caja','activo'),('4101','Ventas','ingreso'),
                                   ('5101','Capital Social','patrimonio'),('2101','Mercaderías','activo')]:
            with self.subTest(codigo=codigo), self.assertRaises(ValueError): validar_cuenta(codigo,nombre,tipo)
        for codigo,nombre,tipo in [('101','Caja','activo'),('70','Ventas','ingreso'),('50','Capital','patrimonio'),('20','Mercaderías','activo')]:
            validar_cuenta(codigo,nombre,tipo)

    def test_creacion_y_edicion_comparten_validacion_y_no_producen_500(self):
        guardar_importacion(novatech()[:6])
        cuenta = CuentaContable.objects.get(codigo='101')
        capital = CuentaContable.objects.get(codigo='50')
        asiento = AsientoContable.objects.first()
        base = {'fecha':'2025-10-31','descripcion':'Aporte', 'num_movimientos':'2',
                'cuenta_0':str(cuenta.pk),'cuenta_1':str(capital.pk),'tipo_0':'debe','tipo_1':'haber',
                'monto_0':'100','monto_1':'100'}
        ids=list(AsientoContable.objects.values_list('pk',flat=True))
        for cambio in ({'num_movimientos':'oops'},{'num_movimientos':'999999'}, {'fecha':'2025-02-30'},
                       {'monto_0':'NaN'}, {'monto_0':'Infinity'}, {'monto_0':'0'}, {'monto_0':'-1'},
                       {'monto_0':'1.001'},{'monto_0':'10000000000'},{'monto_0':'99'},{'cuenta_0':'-1'}):
            for ruta in (reverse('registrar_asiento'),reverse('editar_asiento',args=[asiento.pk])):
                r=self.client.post(ruta,{**base,**cambio})
                self.assertLess(r.status_code,500)
                self.assertEqual(list(AsientoContable.objects.values_list('pk',flat=True)),ids)
                self.assertEqual(AsientoContable.objects.first().total_debe,30000)

    def test_respaldo_incluye_catalogo_sin_movimientos_y_restauracion_exacta(self):
        guardar_importacion(novatech()[:6])
        CuentaContable.objects.create(codigo='1041',nombre='Banco',tipo='activo')
        antes=list(CuentaContable.objects.values_list('codigo','nombre','tipo'))
        guardar_importacion(novatech()[:1])
        respaldo=RespaldoCaso.objects.latest('pk')
        self.assertEqual(len(respaldo.datos),6)
        self.assertTrue(any(c['codigo']=='1041' for c in respaldo.catalogo))
        r=self.client.post(reverse('restaurar_respaldo',args=[respaldo.pk]))
        self.assertEqual(r.status_code,302)
        self.assertEqual(AsientoContable.objects.count(),6)
        self.assertEqual(list(CuentaContable.objects.values_list('codigo','nombre','tipo')),antes)

    def test_ratios_caso_separados_nd_y_csv(self):
        guardar_importacion(novatech()[:6])
        r=self.client.get(reverse('ratios_caso'))
        self.assertContains(r,'N/D')
        reporte=r.context['resultado']
        self.assertEqual(reporte['values']['current'],11)
        self.assertIsNone(reporte['values']['roe'])
        self.assertIsNone(reporte['values']['roa'])
        self.assertIsNone(reporte['values']['receivable_days'])
        filas=list(csv.reader(StringIO(self.client.get(reverse('ratios_caso')+'?descargar=csv').content.decode('utf-8-sig'))))
        self.assertEqual(len(filas),19)

    def test_smtp_falla_pero_descarga_pdf_no_expone_error(self):
        guardar_importacion(novatech()[:6])
        with patch('core.views.EmailMessage.send',side_effect=RuntimeError('SECRET=privado')):
            r=self.client.post(reverse('reporte_completo'), {'empresa':'Prueba','accion':'enviar_correo','correo':'a@example.com'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r['X-Report-Email-Status'],'failed')
        self.assertTrue(PdfReader(BytesIO(r.content)).pages)
        self.assertNotIn(b'privado',r.content)


@override_settings(WORKSPACE_ISOLATION=True, AI_REQUIRE_LOGIN=False)
class AislamientoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a,self.b=Client(),Client()
        self.a.get(reverse('index'));self.b.get(reverse('index'))
        token=actual.set(self.a.session['workspace_id'])
        try: guardar_importacion(novatech()[:6])
        finally: actual.reset(token)

    def test_lectura_edicion_borrado_y_exportacion_no_cruzan_espacios(self):
        a=self.a.get(reverse('libro_diario'))
        self.assertEqual(len(a.context['asientos']),6)
        b=self.b.get(reverse('libro_diario'))
        self.assertEqual(len(b.context['asientos']),0)
        pk=a.context['asientos'][0].pk
        self.assertEqual(self.b.post(reverse('eliminar_asiento',args=[pk])).status_code,404)
        self.assertEqual(self.b.post(reverse('editar_asiento',args=[pk]),{}).status_code,404)
        self.assertEqual(self.a.get(reverse('eliminar_asiento',args=[pk])).status_code,405)
        xlsx=self.b.post(reverse('reporte_completo'),{'formato':'excel'})
        libro=load_workbook(BytesIO(xlsx.content),data_only=True)
        self.assertNotIn('Aporte inicial',' '.join(str(c.value) for row in libro['Libro Diario'] for c in row))
        self.assertEqual(len(self.a.get(reverse('libro_diario')).context['asientos']),6)

    def test_csrf_requerido_y_limite_de_consumo(self):
        seguro=Client(enforce_csrf_checks=True)
        seguro.get(reverse('index'))
        self.assertEqual(seguro.post(reverse('registrar_asiento'),{}).status_code,403)
        with patch('core.views.Groq'):
            for _ in range(12): self.b.post(reverse('chatbot_api'), {'message':''})
            r=self.b.post(reverse('chatbot_api'),{'message':''})
        self.assertEqual(r.status_code,429)
        self.assertEqual(r['Retry-After'],'60')

    def test_historico_sin_propietario_no_se_publica(self):
        CuentaContable.objects.create(codigo='1101',nombre='Caja histórica',tipo='activo')
        self.assertNotContains(self.a.get(reverse('gestionar_cuentas')),'Caja histórica')
        self.assertNotContains(self.b.get(reverse('gestionar_cuentas')),'Caja histórica')


@override_settings(WORKSPACE_ISOLATION=True)
class AutenticacionPersistenciaTests(TestCase):
    def test_ia_exige_cuenta_y_espacio_persiste_entre_sesiones(self):
        from django.contrib.auth import get_user_model
        user=get_user_model().objects.create_user('audit_user',password='ContraseñaSegura123!')
        c=Client();c.get(reverse('index'))
        self.assertEqual(c.post(reverse('chatbot_api'),{'message':'Hola'}).status_code,401)
        c.force_login(user);c.get(reverse('index'))
        token=actual.set(c.session['workspace_id'])
        try: guardar_importacion(novatech()[:6])
        finally: actual.reset(token)
        otro=Client();otro.force_login(user)
        self.assertEqual(len(otro.get(reverse('libro_diario')).context['asientos']),6)
        otro.post(reverse('logout'))
        self.assertEqual(len(otro.get(reverse('libro_diario')).context['asientos']),0)

    def test_respaldos_ajenos_no_se_descargan_ni_restauran(self):
        a,b=Client(),Client();a.get(reverse('index'));b.get(reverse('index'))
        token=actual.set(a.session['workspace_id'])
        try:
            guardar_importacion(novatech()[:6]);guardar_importacion(novatech()[:1])
            pk=RespaldoCaso.objects.latest('pk').pk
        finally: actual.reset(token)
        self.assertEqual(b.get(reverse('descargar_respaldo',args=[pk])).status_code,404)
        self.assertEqual(b.post(reverse('restaurar_respaldo',args=[pk])).status_code,404)
        self.assertEqual(len(a.get(reverse('libro_diario')).context['asientos']),1)

    def test_adopcion_historica_es_simulacion_por_defecto(self):
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from core.models import Workspace
        get_user_model().objects.create_user('historico')
        cuenta=CuentaContable.objects.create(codigo='1101',nombre='Caja original',tipo='activo')
        salida=StringIO()
        call_command('asignar_historico',usuario='historico',stdout=salida)
        cuenta.refresh_from_db();self.assertIsNone(cuenta.workspace_id)
        call_command('asignar_historico',usuario='historico',confirmar=True,stdout=salida)
        cuenta.refresh_from_db();self.assertIsNotNone(cuenta.workspace_id)
        self.assertEqual(cuenta.codigo,'1101')
        self.assertEqual(cuenta.nombre,'Caja original')


class BotDatosRealesTests(TestCase):
    def test_resultados_del_caso_sin_alucinacion_ni_proveedor(self):
        guardar_importacion(novatech()[:6])
        with patch('core.views.Groq') as proveedor:
            r=self.client.post(reverse('chatbot_api'),{'message':'¿Cuál es mi utilidad neta?'})
            self.assertEqual(r.json()['status'],'calculated')
            self.assertIn('12,000.00',r.json()['response'])
            b=self.client.post(reverse('chatbot_api'),{'message':'¿Mi balance está cuadrado?'})
            self.assertIn('45,000.00',b.json()['response'])
            self.assertIn('42,000.00',b.json()['response'])
            proveedor.assert_not_called()

    def test_error_de_api_no_expone_detalles_y_seguimiento_tiene_contexto(self):
        from types import SimpleNamespace
        from django.test import override_settings
        respuesta=lambda v: SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=v))])
        with override_settings(GROQ_API_KEY='prueba'), patch('core.views.Groq') as proveedor:
            proveedor.return_value.chat.completions.create.side_effect=[respuesta('{"permitida":true}'),respuesta('Un activo es un recurso.'),respuesta('{"permitida":true}'),respuesta('Por ejemplo, Caja.')]
            self.client.post(reverse('chatbot_api'),{'message':'¿Qué es un activo?'})
            self.client.post(reverse('chatbot_api'),{'message':'¿Un ejemplo?'})
            prompt=proveedor.return_value.chat.completions.create.call_args.kwargs['messages'][0]['content']
            self.assertIn('Un activo es un recurso.',prompt)
            proveedor.return_value.chat.completions.create.side_effect=RuntimeError('gsk_CLAVE_PRIVADA datos internos')
            r=self.client.post(reverse('chatbot_api'),{'message':'Explica los activos'})
            self.assertNotIn('gsk_',r.content.decode())
            self.assertNotIn('datos internos',r.content.decode())


class InventarioManualTests(TestCase):
    def test_ajuste_manual_valida_con_saldo_previo_no_con_saldo_cero(self):
        guardar_importacion([
            {'fecha':'2025-10-01','descripcion':'Aporte','movimientos':[
                {'codigo':'10','nombre':'Caja','tipo_cuenta':'activo','tipo_movimiento':'debe','monto':'10000'},
                {'codigo':'50','nombre':'Capital','tipo_cuenta':'patrimonio','tipo_movimiento':'haber','monto':'10000'}]},
            {'fecha':'2025-10-02','descripcion':'Compra mercadería','movimientos':[
                {'codigo':'20','nombre':'Mercaderías','tipo_cuenta':'activo','tipo_movimiento':'debe','monto':'5000'},
                {'codigo':'10','nombre':'Caja','tipo_cuenta':'activo','tipo_movimiento':'haber','monto':'5000'}]}])
        inventario=CuentaContable.objects.get(codigo='20')
        costo=CuentaContable.objects.create(codigo='69',nombre='Costo de ventas',tipo='gasto',subcategoria='costo_ventas')
        datos={'fecha':'2025-10-31','descripcion':'Ajuste inventario físico final S/ 2,000', 'num_movimientos':2,
               'cuenta_0':costo.pk,'tipo_0':'debe','monto_0':'3000',
               'cuenta_1':inventario.pk,'tipo_1':'haber','monto_1':'3000'}
        r=self.client.post(reverse('registrar_asiento'),datos)
        self.assertRedirects(r,reverse('libro_diario'))
        self.assertEqual(AsientoContable.objects.count(),3)
        self.assertEqual(contexto_estados()['total_costo_ventas'],3000)
        self.assertFalse(contexto_estados()['notas_consistencia'])
        a=AsientoContable.objects.order_by('fecha').last()
        r=self.client.post(reverse('editar_asiento',args=[a.pk]),datos)
        self.assertRedirects(r,reverse('libro_diario'))
        self.assertEqual(AsientoContable.objects.count(),3)
