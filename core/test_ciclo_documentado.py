"""Regresión del caso con apertura, IVA y letras aportado por el usuario."""
import json
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import load_workbook
from pypdf import PdfReader
from .ciclo_contable import generar_asientos
from .models import AsientoContable
from .reporte_utils import contexto_estados
from .test_ciclo_contable import imagen


def caso_letras():
    return json.loads((Path(__file__).parent / 'testdata/caso_letras_2023.json').read_text())


class CicloDocumentadoTests(SimpleTestCase):
    def test_apertura_y_cada_operacion(self):
        asientos = generar_asientos(caso_letras())
        esperado = [
            [('101','debe','2500000'),('1041','debe','3500000'),('121','debe','600000'),('421','haber','800000'),('50','haber','5800000')],
            [('20','debe','847457.63'),('4011','debe','152542.37'),('423','haber','1000000')],
            [('101','debe','188800'),('123','debe','283200'),('70','haber','400000'),('4011','haber','72000')],
            [('63','debe','100000'),('1041','haber','100000')],
            [('421','debe','400000'),('1041','haber','400000')],
            [('1041','debe','141600'),('123','haber','141600')],
            [('423','debe','300000'),('1041','haber','300000')],
        ]
        actual = [[(m['codigo'],m['tipo_movimiento'],m['monto']) for m in a['movimientos']] for a in asientos]
        self.assertEqual(actual, [[(c,t,Decimal(m)) for c,t,m in lineas] for lineas in esperado])
        self.assertEqual([a['fecha'].isoformat() for a in asientos], ['2023-06-01','2023-06-01','2023-06-02','2023-06-10','2023-06-11','2023-06-15','2023-06-30'])
        self.assertEqual(sum(m['monto'] for a in asientos for m in a['movimientos'] if m['tipo_movimiento']=='debe'), Decimal('9013600'))

    def test_tasa_configurable_y_tasa_explicita(self):
        datos = caso_letras(); datos['tasa_impuesto_configurada']='19'
        asientos=generar_asientos(datos)
        self.assertEqual(asientos[1]['movimientos'][0]['monto'],Decimal('840336.13'))
        self.assertEqual(asientos[2]['movimientos'][0]['monto'],Decimal('190400'))
        for op in datos['operaciones'][:2]: op['tasa_impuesto']='18'
        self.assertEqual(generar_asientos(datos),generar_asientos(caso_letras()))

    def test_importes_distintos_y_redondeo_no_pierden_centimos(self):
        datos=caso_letras(); datos['operaciones'][0]['monto']='1000000.03'
        asientos=generar_asientos(datos)
        self.assertEqual(asientos[-1]['movimientos'][0]['monto'],Decimal('300000'))
        for a in asientos:
            self.assertEqual(sum(m['monto'] for m in a['movimientos'] if m['tipo_movimiento']=='debe'),sum(m['monto'] for m in a['movimientos'] if m['tipo_movimiento']=='haber'))
        datos['operaciones'][0]['monto']=2000000
        self.assertEqual(generar_asientos(datos)[-1]['movimientos'][0]['monto'],Decimal('600000'))

    def test_errores_rechazados_antes_de_guardar(self):
        cambios=[lambda d:d['saldos_apertura'][-1].update(monto=5800001),
                 lambda d:d['operaciones'][4].update(letras_numeros=['999']),
                 lambda d:d['operaciones'][5].update(cantidad_letras=11),
                 lambda d:d['operaciones'][2].update(medio_pago=None),
                 lambda d:d.update(tasa_impuesto_configurada=None),
                 lambda d:d.update(fecha_apertura='2023-06-03')]
        for cambiar in cambios:
            datos=caso_letras();cambiar(datos)
            with self.subTest(datos=datos), self.assertRaises(ValueError):generar_asientos(datos)
        datos=caso_letras();duplicado=deepcopy(datos['operaciones'][4]);duplicado['fecha']='2023-06-20';datos['operaciones'].append(duplicado)
        with self.assertRaises(ValueError):generar_asientos(datos)

    def test_letras_desiguales_requieren_identificacion_para_pagar(self):
        datos=caso_letras();datos['operaciones'][0]['letras_importes']=[50000,150000]+[100000]*8
        with self.assertRaises(ValueError):generar_asientos(datos)


class ImportacionDocumentadaTests(TestCase):
    def confirmar_parcial(self, response):
        import json
        self.assertContains(response, 'Revisar ejercicio')
        self.assertTrue(response.context['pendientes'])
        return self.client.post(reverse('revisar_importacion'), {
            'revision_token': response.context['revision_token'],
            'asientos_json': json.dumps(response.context['asientos']),
            'revisado': 'on', 'aceptar_parcial': 'on'})

    def importar(self):
        with patch('core.ai_diario.extraer_operaciones',return_value=caso_letras()):
            response=self.client.post(reverse('cargar_imagen_diario'),{'imagen_caso':imagen(),'limpiar':'on','tasa_impuesto':'18'})
        self.assertEqual(AsientoContable.objects.count(),0)
        response=self.confirmar_parcial(response)
        self.assertRedirects(response,reverse('libro_diario'))
        self.assertEqual(AsientoContable.objects.count(),7)

    def test_saldos_banco_caja_impuesto_y_resultado_provisional(self):
        self.importar();ctx=contexto_estados()
        saldos={item['cuenta'].codigo:item['saldo'] for item in ctx['activo_corriente']}
        self.assertEqual(saldos,{'101':Decimal('2688800'),'1041':Decimal('2841600'),'121':Decimal('600000'),'123':Decimal('141600'),'20':Decimal('847457.63'),'4011':Decimal('80542.37')})
        self.assertEqual(ctx['total_activos'],Decimal('7200000'))
        self.assertEqual(ctx['total_pasivos'],Decimal('1100000'))
        self.assertEqual(ctx['total_patrimonio_con_resultados'],Decimal('6100000'))
        self.assertTrue(ctx['esta_balanceado'])
        self.assertIn('resultado es provisional',ctx['nota_resultado'])
        self.assertContains(self.client.get(reverse('estado_resultados')),'resultado es provisional')
        datos=caso_letras();datos['operaciones'][0]['monto']=100000
        with patch('core.ai_diario.extraer_operaciones',return_value=datos):
            response=self.client.post(reverse('cargar_imagen_diario'),{'imagen_caso':imagen(),'limpiar':'on','tasa_impuesto':'18'})
        self.assertRedirects(self.confirmar_parcial(response),reverse('libro_diario'))
        nuevo=contexto_estados()
        self.assertEqual(nuevo['total_pasivos'],Decimal('526745.76'))
        self.assertNotIn('4011',{i['cuenta'].codigo for i in nuevo['activo_corriente']})

    def test_reportes_documentados_y_advertencia(self):
        self.importar()
        response=self.client.post(reverse('reporte_completo'),{'formato':'excel','accion':'descargar','empresa':'Caso letras'})
        wb=load_workbook(BytesIO(response.content))
        textos=[str(c.value) for row in wb['Estado de Resultados'] for c in row if c.value is not None]
        self.assertTrue(any('resultado es provisional' in t for t in textos))
        response=self.client.post(reverse('reporte_completo'),{'formato':'pdf','accion':'descargar','empresa':'Caso letras'})
        self.assertEqual(response.status_code,200)
        texto=' '.join(p.extract_text() for p in PdfReader(BytesIO(response.content)).pages)
        self.assertIn('resultado es provisional',texto)

    def test_apertura_invalida_conserva_datos_previos(self):
        self.importar();ids=list(AsientoContable.objects.values_list('pk',flat=True))
        datos=caso_letras();datos['saldos_apertura'][-1]['monto']=1
        with patch('core.ai_diario.extraer_operaciones',return_value=datos):
            response=self.client.post(reverse('cargar_imagen_diario'),{'imagen_caso':imagen(),'limpiar':'on','tasa_impuesto':'18'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Revisar ejercicio')
        self.assertEqual(list(AsientoContable.objects.values_list('pk',flat=True)),ids)
