"""Fuente FY2025 verificada, ausencia de datos y coherencia de presentación."""
from copy import deepcopy
from unittest.mock import patch
import csv
from io import StringIO
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from .ratios import comparison, dataset
from scripts.build_financial_dataset import apply_verified_inputs


class DatosVerificadosTests(SimpleTestCase):
    def periodo(self):
        return deepcopy(next(p for c in dataset()['companies'] if c['ticker']=='AVGO' for p in c['periods'] if p['year']==2025))

    def test_constructor_reproduce_correccion_publicada_con_fuente(self):
        original = self.periodo()
        vacio = deepcopy(original)
        vacio['values']['net_income'] = None
        vacio['provenance'].pop('net_income', None)
        reconstruido = apply_verified_inputs('AVGO', vacio)
        self.assertEqual(reconstruido['values']['net_income'], '23126')
        self.assertEqual(reconstruido['provenance']['net_income'], original['provenance']['net_income'])
        self.assertTrue(reconstruido['provenance']['net_income']['verified'])
        self.assertNotIn('excluded_value', reconstruido['provenance']['net_income'])

    def test_verificacion_no_se_propaga_a_otra_empresa_periodo_o_moneda(self):
        for ticker, cambios in [('AMD', {}), ('AVGO', {'start':'2024-11-01'}),
                                ('AVGO', {'end':'2025-11-01'}), ('AVGO', {'year':2024}),
                                ('AVGO', {'currency':'EUR'})]:
            with self.subTest(ticker=ticker, cambios=cambios):
                p = self.periodo()
                p.update(cambios)
                p['values']['net_income'] = None
                self.assertIsNone(apply_verified_inputs(ticker,p)['values']['net_income'])

    def test_utilidad_desconocida_cero_perdida_y_ganancia_se_distinguen(self):
        for utilidad, estado in [(None,'Datos pendientes'),('0','Resultado neto cero'),
                                  ('-1','Pérdida contable'),('1','Utilidad positiva')]:
            with self.subTest(utilidad=utilidad):
                companies = deepcopy(dataset()['companies'])
                for p in companies[0]['periods']:
                    if p['year']==2025: p['values']['net_income']=utilidad
                r = comparison(companies)
                self.assertEqual(r['diagnoses'][2]['status'], estado)
                if utilidad is None:
                    self.assertIsNone(r['selected']['values']['net_margin'])
                    self.assertIsNone(r['selected']['values']['roe'])

    def test_verificacion_respeta_el_corte_de_disponibilidad(self):
        p=self.periodo()
        p['values']['net_income']=None
        with patch('scripts.build_financial_dataset.CUTOFF','2025-12-17'):
            self.assertIsNone(apply_verified_inputs('AVGO',p)['values']['net_income'])

    def test_liquidez_no_evaluable_no_afirma_cobertura(self):
        companies = deepcopy(dataset()['companies'])
        companies[0]['periods'][-1]['values']['current_liabilities']=None
        r = comparison(companies)
        self.assertEqual(r['diagnoses'][0]['status'], 'Datos pendientes')
        self.assertNotIn('cubre N/D', r['diagnoses'][0]['text'])


@override_settings(WORKSPACE_ISOLATION=True)
class PantallaVerificadaTests(TestCase):
    def test_broadcom_muestra_17_ratios_margen_roe_y_dupont_con_fuente(self):
        r = self.client.get(reverse('ratios_financieros'))
        self.assertEqual(r.status_code,200)
        filas = {fila['key']:fila for fila in r.context['rows']}
        self.assertEqual(len(filas),17)
        self.assertTrue(all(fila['own']!='N/D' for fila in filas.values()))
        self.assertEqual(filas['net_margin']['own'],'36.20%')
        self.assertEqual(filas['roe']['own'],'31.05%')
        self.assertTrue(r.context['dupont']['matches'])
        self.assertContains(r,'Verificado en el 10-K FY2025')

    def test_csv_conserva_sus_17_valores_y_los_supuestos_visibles(self):
        ruta=reverse('ratios_financieros')
        pantalla=self.client.get(ruta)
        csv_response=self.client.get(ruta,{'descargar':'csv'})
        filas=list(csv.reader(StringIO(csv_response.content.decode('utf-8-sig'))))
        self.assertEqual(len(filas[3:20]),17)
        self.assertIn('36.20%',filas[16])  # Margen neto: indicador 14.
        self.assertEqual(filas[19][3], '31.05%')
        texto=csv_response.content.decode('utf-8-sig')
        for supuesto in pantalla.context['selected']['assumptions']:
            self.assertIn(supuesto,texto)
        self.assertIn('avgo-20251102.htm',texto)
        self.assertIn('no es la tasa efectiva',texto)

    def test_tasa_roa_seleccionada_coincide_en_texto_calculo_y_csv(self):
        ruta=reverse('ratios_financieros')
        pantalla=self.client.get(ruta,{'tasa':'25'})
        self.assertContains(pantalla,'tasa académica seleccionada (25%)')
        self.assertNotContains(pantalla,'taller (30%)')
        from decimal import Decimal
        esperado=Decimal('25484')*Decimal('.75')/((Decimal('171092')+Decimal('165645'))/2)
        self.assertAlmostEqual(pantalla.context['selected']['values']['roa'],esperado,places=20)
        csv_response=self.client.get(ruta,{'tasa':'25','descargar':'csv'})
        filas=list(csv.reader(StringIO(csv_response.content.decode('utf-8-sig'))))
        self.assertIn('25%',filas[1])
        roa=next(f for f in pantalla.context['rows'] if f['key']=='roa')
        self.assertEqual(filas[18][3],roa['own'])

    def test_csv_de_datos_manuales_no_atribuye_sus_cifras_a_sec(self):
        ruta=reverse('ratios_financieros')
        periodo=deepcopy(dataset()['companies'][0]['periods'][-1])
        fuente='https://example.org/estado-verificado-por-el-usuario'
        payload={**periodo['values'],'ticker':'AVGO','name':'Broadcom','industry':'Chips',
            'year':2025,'currency':'USD','period_start':periodo['start'],'period_end':periodo['end'],
            'previous_end':periodo['previous_end'],'source_url':fuente}
        r=self.client.post(ruta,payload,follow=True)
        self.assertEqual(r.status_code,200)
        self.assertContains(r,'Datos guardados')
        csv_response=self.client.get(ruta,{'descargar':'csv'})
        filas=list(csv.reader(StringIO(csv_response.content.decode('utf-8-sig'))))
        inicio=filas.index(['Fuentes y cierres'])
        linea=next(f for f in filas[inicio+1:] if f and f[0]=='AVGO')
        self.assertEqual(linea[4],fuente)
        self.assertEqual(linea[5],'Datos ingresados por el usuario')
