"""Los gráficos reutilizan los resultados de la tabla, sin nuevas fórmulas."""
from copy import deepcopy
from decimal import Decimal as D
from django.test import SimpleTestCase, TestCase, override_settings
from .ratios import comparison, dataset


class RatioVisualDataTests(SimpleTestCase):
    def test_comparacion_y_evolucion_coinciden_con_las_17_filas(self):
        report=comparison(dataset()['companies'])
        for row in report['rows']:
            with self.subTest(indicador=row['key']):
                chart=report['chart_data'][row['key']]
                self.assertEqual([p['display'] for p in chart['benchmarks']], [row['own'],row['leader'],row['sector']])
                self.assertEqual([p['year'] for p in chart['history']],[2024,2025])
                self.assertEqual(chart['history'][0]['series'][0]['display'],row['previous'])
                self.assertEqual([p['display'] for p in chart['history'][-1]['series']],[row['own'],row['leader'],row['sector']])
                self.assertEqual(chart['history'][-1]['n'],row['n'])

    def test_ejercicio_sin_antecedente_no_inventa_anos_o_ttm(self):
        report=comparison(dataset()['companies'],year=2024)
        for chart in report['chart_data'].values():self.assertEqual([p['year'] for p in chart['history']],[2024])

    def test_conversion_asml_identica_en_las_tres_vistas(self):
        report=comparison(dataset()['companies'],'ASML')
        row=next(r for r in report['rows'] if r['key']=='working_capital');chart=report['chart_data']['working_capital']
        self.assertEqual(chart['unit'],'USD MM')
        self.assertEqual(chart['history'][0]['series'][0]['display'],row['previous'])
        self.assertEqual(chart['benchmarks'][0]['display'],row['own'])
        self.assertEqual(chart['history'][1]['series'][0]['display'],row['own'])

    def test_no_disponible_permanece_null_en_el_grafico(self):
        companies=deepcopy(dataset()['companies'])
        for period in companies[0]['periods']:period['values']['net_income']=None
        chart=comparison(companies)['chart_data']['net_margin']
        self.assertIsNone(chart['benchmarks'][0]['value']);self.assertEqual(chart['benchmarks'][0]['display'],'N/D')
        for period in chart['history']:self.assertIsNone(period['series'][0]['value'])

    def test_promedio_historico_respeta_grupo_y_datos_disponibles(self):
        companies=dataset()['companies'];report=comparison(companies,group='chips')
        previous=comparison(companies,year=2024,group='chips')
        for row in previous['rows']:
            chart=report['chart_data'][row['key']]
            self.assertEqual(chart['history'][0]['series'][2]['display'],row['sector'])
            self.assertEqual(chart['history'][0]['n'],row['n'])

    def test_cero_y_perdidas_conservan_su_signo(self):
        companies=deepcopy(dataset()['companies'])
        for period in companies[0]['periods']:
            period['values'].update(net_income='-100',current_assets='10',current_liabilities='10')
        report=comparison(companies)
        self.assertEqual(report['chart_data']['working_capital']['benchmarks'][0]['value'],0)
        self.assertLess(report['chart_data']['net_margin']['benchmarks'][0]['value'],0)
        self.assertTrue(all(p['series'][0]['value']<0 for p in report['chart_data']['net_margin']['history']))


@override_settings(WORKSPACE_ISOLATION=True)
class RatioVisualLayoutTests(TestCase):
    def test_graficos_visibles_antes_de_la_tabla_y_metodo_plegado(self):
        r=self.client.get('/ratios-financieros/');self.assertEqual(r.status_code,200)
        html=r.content.decode()
        self.assertLess(html.index('id="ratio-visual"'),html.index('id="comparativo"'))
        self.assertIn('id="ratio-method-details"',html)
        self.assertNotIn('id="ratio-method-details" open',html)
        self.assertContains(r,'Ver gráficos')
        self.assertContains(r,'data-chart-view="history"')
