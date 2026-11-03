from datetime import date
from decimal import Decimal
from io import BytesIO

from django.test import SimpleTestCase,TestCase,override_settings
from openpyxl import load_workbook
from pypdf import PdfReader

from .ratios import dataset,comparison,FX


class DatosHistoricosTests(SimpleTestCase):
    def test_cobertura_2022_al_corte_y_solo_anuales_publicados(self):
        data=dataset()
        self.assertEqual((data['coverage_start'],data['coverage_end']),(2022,2026))
        self.assertEqual(len(data['companies']),9)
        for company in data['companies']:
            years=[p['year'] for p in company['periods']]
            self.assertEqual(len(years),len(set(years)))
            self.assertTrue({2022,2023,2024,2025}.issubset(years))
            for p in company['periods']:
                self.assertTrue(300 <= (date.fromisoformat(p['end'])-date.fromisoformat(p['start'])).days <= 380)
                self.assertLessEqual(p['end'],data['as_of'])
                for source in p['provenance'].values():
                    if source.get('filed'):self.assertLessEqual(source['filed'],data['as_of'])

    def test_2026_existe_solo_para_las_empresas_con_informe_publicado(self):
        companies=dataset()['companies']
        available={c['ticker'] for c in companies if any(p['year']==2026 for p in c['periods'])}
        self.assertEqual(available,{'NVDA','LRCX','CSCO','KLAC'})
        report=comparison(companies,'NVDA',year=2026)
        self.assertEqual(report['selected']['inputs']['revenue'],215938)
        self.assertEqual(report['peer_count'],4)
        self.assertEqual([p['year'] for p in report['chart_data']['net_margin']['history']],[2022,2023,2024,2025,2026])

    def test_cada_punto_del_historico_coincide_con_el_reporte_de_su_ano(self):
        companies=dataset()['companies']
        history=comparison(companies)['chart_data']
        for year in range(2022,2026):
            report=comparison(companies,year=year)
            for row in report['rows']:
                point=next(p for p in history[row['key']]['history'] if p['year']==year)
                self.assertEqual([x['display'] for x in point['series']],[row['own'],row['leader'],row['sector']])
                self.assertEqual(point['n'],row['n'])

    def test_fuentes_y_conversion_2022_2023_sin_cotizaciones_inventadas(self):
        self.assertEqual(FX[2022],Decimal('1.0666'))
        self.assertEqual(FX[2023],Decimal('1.1050'))
        for year in (2022,2023):
            report=comparison(dataset()['companies'],'ASML',year=year)
            values=report['selected']['inputs']
            amount=(values['current_assets']-values['current_liabilities'])*FX[year]
            row=next(r for r in report['rows'] if r['key']=='working_capital')
            self.assertEqual(row['numbers']['own'],amount)
        intel=next(c for c in dataset()['companies'] if c['ticker']=='INTC')
        for p in intel['periods']:
            if p['year'] in (2022,2023):self.assertTrue(p['provenance']['cash']['verified'])


@override_settings(WORKSPACE_ISOLATION=True)
class PantallaHistoricaTests(TestCase):
    def test_sin_2026_no_cambia_la_empresa_ni_etiqueta_2025_como_2026(self):
        r=self.client.get('/ratios-financieros/',{'empresa':'AMD','year':'2026'})
        self.assertEqual(r.context['ticker'],'AMD')
        self.assertEqual(r.context['year'],2025)
        self.assertContains(r,'No hay informe anual FY2026 disponible para AMD')

    def test_pantalla_y_descargas_permiten_2022_y_2026_disponible(self):
        for ticker,year in [('AVGO',2022),('AVGO',2023),('NVDA',2026)]:
            with self.subTest(ticker=ticker,year=year):
                query={'empresa':ticker,'year':year}
                r=self.client.get('/ratios-financieros/',query)
                self.assertEqual(r.context['year'],year)
                self.assertEqual(len(r.context['rows']),17)
                x=self.client.get('/ratios-financieros/',{**query,'descargar':'xlsx'})
                book=load_workbook(BytesIO(x.content),data_only=True)
                self.assertEqual(book['17 indicadores'].max_row,23)
                pdf=self.client.get('/ratios-financieros/',{**query,'descargar':'pdf'})
                text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
                self.assertIn(f'FY{year}',text)
