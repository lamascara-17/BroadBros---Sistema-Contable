"""Validación contra el Excel del docente y estados públicos, no salidas de IA."""
import json
from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from django.test import TestCase, SimpleTestCase, Client
from .test_support import AdministrativeTestCase as TestCase, AdministrativeSimpleTestCase as SimpleTestCase
from django.urls import reverse
from .models import FinancialRatioPeriod, CuentaContable, AsientoContable
from .ratios import calculate, comparison, dataset, companies_with_overrides, DEFINITIONS, number
from .ratio_views import FinancialInputsForm, safe_csv


class RatioCalculationTests(SimpleTestCase):
    def professor(self):
        return json.loads((Path(__file__).parent/'data/professor_ratio_fixture.json').read_text())

    def test_17_indicadores_coinciden_con_excel_alicorp_2016(self):
        fixture = self.professor()
        actual = calculate(fixture['inputs'])
        self.assertEqual(len(DEFINITIONS),17)
        self.assertEqual(len(fixture['expected']),17)
        for key, expected in fixture['expected'].items():
            with self.subTest(ratio=key):
                self.assertLess(abs(actual['values'][key]-D(str(expected))),D('0.000000001'))

    def test_faltantes_ceros_y_negativos_no_producen_infinito_ni_cero_falso(self):
        for value in (None, '0', '-1'):
            v = self.professor()['inputs']
            v.update(current_liabilities=value,assets=value,assets_previous=value,
                     equity=value,equity_previous=value,total_equity=value)
            actual = calculate(v)
            for key in ('current','quick','roa','roe','leverage'):
                self.assertIsNone(actual['values'][key])
        self.assertTrue(all(v is None for v in calculate({})['values'].values()))

    def test_perdida_valida_y_ebitda_negativo(self):
        v = self.professor()['inputs']
        v.update(net_income='-100',operating_income='-1000',da='50')
        actual = calculate(v)
        self.assertLess(actual['values']['net_margin'],0)
        self.assertLess(actual['values']['roe'],0)
        self.assertIsNone(actual['values']['debt_cover'])
        self.assertLess(actual['values']['interest_cover'],0)

    def test_base_cp_y_credito_explicito_cambian_solo_los_ratios_correspondientes(self):
        v = self.professor()['inputs']
        normal = calculate(v)
        v.update(credit_revenue=D(str(v['revenue']))/2,credit_purchases=D(str(v['cost_sales']))/2)
        actual = calculate(v,debt_basis='current')
        self.assertAlmostEqual(actual['values']['receivable_days'],normal['values']['receivable_days']*2,places=20)
        self.assertAlmostEqual(actual['values']['payable_days'],normal['values']['payable_days']*2,places=20)
        self.assertAlmostEqual(actual['values']['debt_cover'],D(str(v['debt_current']))/actual['ebitda'],places=20)
        self.assertEqual(actual['assumptions'],[])

    def test_datos_no_finitos_y_booleanos_se_rechazan(self):
        for value in ('NaN','Infinity','-Infinity',True,'1e999','1e-999'):
            with self.subTest(value=value), self.assertRaises(ValueError):number(value)

    def test_broadcom_2025_y_dupont_concilian(self):
        report = comparison(dataset()['companies'])
        v = report['selected']['values']
        self.assertEqual(report['selected']['ebitda'],34120)
        self.assertAlmostEqual(v['current'],D('31573')/D('18514'),places=20)
        self.assertAlmostEqual(v['net_margin'],D('23126')/D('63887'),places=20)
        self.assertAlmostEqual(v['roe'],D('23126')/((D('81292')+D('67678'))/2),places=20)
        self.assertTrue(report['selected']['period']['provenance']['net_income']['verified'])
        self.assertEqual(report['dupont']['roe'],'31.05%')
        self.assertTrue(report['dupont']['matches'])
        self.assertFalse(report['selected']['warnings'])

    def test_grupo_transparente_media_y_cambio_de_lider(self):
        data = dataset()['companies']
        r = comparison(data,leader='AMD')
        self.assertEqual(r['peer_count'],9)
        self.assertEqual(r['reference']['company']['ticker'],'AMD')
        self.assertEqual(len(r['chart_data']['net_margin']['points']),9)
        ebitda_row = next(row for row in r['rows'] if row['key']=='ebitda_margin')
        self.assertEqual(ebitda_row['n'],8)  # Cisco no se sustituye por cero.
        margins = [p['value'] for p in r['chart_data']['net_margin']['points']]
        own_sector = next(row for row in r['rows'] if row['key']=='net_margin')['sector']
        self.assertEqual(own_sector,f'{sum(margins)/len(margins)*100:.2f}%')
        self.assertEqual(comparison(data,group='chips')['peer_count'],4)
        self.assertEqual(comparison(data,group='equipment')['peer_count'],4)

    def test_conversion_moneda_solo_capital_de_trabajo(self):
        data = dataset()['companies']
        r = comparison(data,ticker='ASML')
        period = r['selected']['period']
        expected = (D(period['values']['current_assets'])-D(period['values']['current_liabilities']))*D('1.1750')
        own = next(row for row in r['rows'] if row['key']=='working_capital')['own']
        self.assertEqual(own,f'{expected:,.2f}')
        self.assertEqual(r['selected']['values']['current'],calculate(period['values'])['values']['current'])

    def test_datos_de_fuente_y_ecuaciones_de_todas_las_empresas(self):
        for company in dataset()['companies']:
            for p in company['periods']:
                with self.subTest(company=company['ticker'],year=p['year']):
                    actual=calculate(p['values'])
                    self.assertFalse(actual['warnings'])
                    self.assertEqual(len([k for k in actual['values'] if not k.startswith('_')]),17)
                    for key,value in p['values'].items():
                        if value is not None:self.assertTrue(p['provenance'][key]['url'].startswith('https://www.sec.gov/'))


class RatioScreenTests(TestCase):
    def payload(self,ticker='AVGO'):
        c=next(c for c in dataset()['companies'] if c['ticker']=='AVGO')
        p=c['periods'][-1]
        return {**{k:v for k,v in p['values'].items() if v is not None},'ticker':ticker,'name':'Empresa editada',
            'industry':'Semiconductores','year':2025,'currency':'USD','period_start':p['start'],
            'period_end':p['end'],'previous_end':p['previous_end'],'source_url':'https://example.com/annual-report'}

    def test_pantalla_17_filas_fecha_iso_navegacion_y_grafico(self):
        r=self.client.get(reverse('ratios_financieros'))
        self.assertEqual(r.status_code,200)
        self.assertEqual(len(r.context['rows']),17)
        self.assertContains(r,'value="2025-11-02"')
        self.assertContains(r,'ratio-chart-data')
        self.assertContains(r,'N/D')
        self.assertContains(self.client.get(reverse('index')),reverse('ratios_financieros'))
        self.assertEqual(FinancialRatioPeriod.objects.count(),0) # GET no escribe.

    def test_cambiar_filtros_y_entradas_get_invalidas_no_rompe(self):
        for params in ({'empresa':'INTC','lider':'KLAC','year':2024},{'tasa':'NaN'},
                       {'year':'no-numero'},{'empresa':'<script>'},{'year':2099},
                       {'empresa':'ASML','grupo':'equipment','deuda':'current'}):
            with self.subTest(params=params):self.assertEqual(self.client.get(reverse('ratios_financieros'),params).status_code,200)

    def test_guardado_persistente_no_modifica_asientos(self):
        CuentaContable.objects.create(codigo='10',nombre='Caja',tipo='activo')
        a=AsientoContable.objects.create(fecha='2026-01-01',descripcion='No borrar')
        response=self.client.post(reverse('ratios_financieros'),self.payload(),follow=True)
        self.assertEqual(response.status_code,200)
        self.assertEqual(FinancialRatioPeriod.objects.count(),1)
        self.assertTrue(AsientoContable.objects.filter(pk=a.pk).exists())
        self.assertEqual(CuentaContable.objects.count(),1)
        self.assertContains(response,'Datos editados')
        self.assertContains(response,'Empresa editada')
        self.assertEqual(len(response.context['rows']),17)

    def test_decima_empresa_se_incorpora_sin_inventar_una(self):
        response=self.client.post(reverse('ratios_financieros'),self.payload('TEST'),follow=True)
        self.assertEqual(response.context['peer_count'],10)
        self.assertEqual(response.context['ticker'],'TEST')
        self.assertEqual(FinancialRatioPeriod.objects.get(ticker='TEST').year,2025)

    def test_datos_invalidos_no_sustituyen_guardado_previo(self):
        self.client.post(reverse('ratios_financieros'),self.payload())
        for updates in ({'total_equity':'1'},{'period_end':'2025-01-01'},{'previous_end':'2025-11-03'},
                        {'revenue':'NaN'},{'cash':'-10'},{'ticker':'<script>'},{'source_url':'javascript:alert(1)'}):
            values={**self.payload(),**updates}
            response=self.client.post(reverse('ratios_financieros'),values)
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(FinancialRatioPeriod.objects.count(),1)
        self.assertEqual(FinancialRatioPeriod.objects.get().values['total_equity'],'81292')

    def test_sin_datos_no_se_guardan_ceros_inventados(self):
        data=self.payload('EMPTY')
        for key in list(data):
            if key in self.payload() and key in dataset()['companies'][0]['periods'][0]['values']:data[key]=''
        response=self.client.post(reverse('ratios_financieros'),data,follow=True)
        self.assertEqual(response.status_code,200)
        self.assertTrue(all(row['own']=='N/D' for row in response.context['rows']))

    def test_csv_respeta_filtros_y_evade_formulas(self):
        r=self.client.get(reverse('ratios_financieros'),{'empresa':'AMD','year':2024,'descargar':'csv'})
        self.assertEqual(r.status_code,200)
        self.assertIn('Ratios_AMD_2024.csv',r['Content-Disposition'])
        self.assertIn('Margen neto',r.content.decode('utf-8-sig'))
        self.assertEqual(safe_csv('=HYPERLINK("x")'),'\'=HYPERLINK("x")')

    def test_post_requiere_csrf(self):
        c=Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(reverse('ratios_financieros'),self.payload()).status_code,403)
