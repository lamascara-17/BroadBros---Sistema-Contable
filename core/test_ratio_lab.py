"""Pruebas numéricas independientes, separación de ámbitos y llamadas públicas."""
from copy import deepcopy
from decimal import Decimal as D
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase, Client, override_settings
from django.core.cache import cache
from .ratio_lab import changes, simulate, explanations, tutor, version
from .ratios import comparison, dataset, calculate
from .models import FinancialRatioPeriod, AsientoContable, CuentaContable
from .workspaces import acceso_administrativo


def example():
    v={'current_assets':'50','current_liabilities':'25','cash':'20','receivables':'10','receivables_previous':'10',
       'inventory':'20','inventory_previous':'10','payables':'10','payables_previous':'8','assets':'200','assets_previous':'100',
       'liabilities':'120','equity':'80','equity_previous':'60','total_equity':'80','debt_current':'10','debt_noncurrent':'20',
       'revenue':'100','cost_sales':'60','operating_income':'20','net_income':'14','interest':'5','da':'5'}
    c={'ticker':'TEST','name':'Empresa de prueba','industry':'Prueba','source_url':'','periods':[{'year':2025,'start':'2025-01-01','end':'2025-12-31','currency':'USD','values':v,'provenance':{}}]}
    return comparison([c],'TEST','TEST')


class RatioLabMathTests(SimpleTestCase):
    def test_escenario_cero_coincide_y_no_muta_partidas(self):
        r=example();before=deepcopy(r)
        s=simulate(r,changes({}),D('.3'),'total')
        self.assertEqual(r,before)
        self.assertEqual(len(s['cards']),8)
        for card in s['cards']: self.assertEqual(card['before'],card['after'])

    def test_ventas_costos_y_deuda_con_aritmetica_independiente(self):
        r=example();s=simulate(r,changes({'ventas':'10','costos':'10','deuda':'50'}),D('.3'),'total')
        cards={c['key']:c for c in s['cards']}
        self.assertEqual(s['inputs']['Ventas netas'],'110')
        self.assertEqual(s['inputs']['Costo de ventas'],'66')
        self.assertEqual(s['inputs']['Utilidad operativa'],'24')
        self.assertEqual(s['inputs']['Utilidad neta atribuible al accionista'],'16.8')
        self.assertEqual(cards['roe']['after'],'24.00%')
        self.assertEqual(cards['roa']['after'],'11.20%')
        self.assertEqual(cards['net_margin']['after'],'15.27%')
        self.assertEqual(cards['debt_cover']['after'],'1.55x')
        self.assertEqual(cards['roe']['delta'],'+4.00 pp')

    def test_deuda_cp_no_agrega_lp_ni_inventa_intereses(self):
        r=example();s=simulate(r,changes({'deuda':'50'}),D('.3'),'current')
        cards={c['key']:c for c in s['cards']}
        self.assertEqual(cards['debt_cover']['after'],'0.60x')
        self.assertEqual(cards['interest_cover']['after'],'5.00x')
        self.assertEqual(cards['net_margin']['after'],'14.00%')

    def test_faltantes_no_se_reconstruyen_como_utilidad(self):
        r=example();r['selected']['inputs']['net_income']=None
        s=simulate(r,changes({'ventas':'10'}),D('.3'),'total')
        cards={c['key']:c for c in s['cards']}
        self.assertEqual(cards['net_margin']['after'],'N/D');self.assertEqual(cards['roe']['after'],'N/D')

    def test_perdidas_y_ebitda_no_positivo(self):
        r=example();s=simulate(r,changes({'ventas':'-50','costos':'50'}),D('.3'),'total')
        c={r['key']:r for r in s['cards']}
        self.assertTrue(c['net_margin']['after'].startswith('-'))
        self.assertEqual(c['debt_cover']['after'],'N/D')
        self.assertIn('negativo',c['debt_cover']['reason'])

    def test_limites_no_finitos_precision_y_booleanos(self):
        for value in ('NaN','Infinity','51','-51','0.123',True,'1e999','1e-999',''):
            with self.subTest(value=value),self.assertRaises(ValueError):changes({'ventas':value})

    def test_trazas_17_con_fuentes_y_supuestos(self):
        r=comparison(dataset()['companies']);d=explanations(r,D('.3'),'total')
        self.assertEqual(len(d),17)
        self.assertEqual(d['roe']['value'],'31.05%')
        self.assertIn('23,126',d['roe']['expression'])
        self.assertTrue(any(i['url'] for i in d['roe']['inputs']))
        self.assertIn('aproximación',d['receivable_days']['notes'][0])
        self.assertIn('académica',d['roa']['notes'][0])
        for row in r['rows']:self.assertEqual(d[row['key']]['value'],row['own'])

    def test_sustituciones_reproducen_los_17_resultados_del_excel(self):
        import ast
        import json
        from pathlib import Path
        fixture=json.loads((Path(__file__).parent/'data/professor_ratio_fixture.json').read_text())
        company=example()['selected']['company']
        company['periods'][0]['values']=fixture['inputs']
        r=comparison([company],'TEST','TEST');trace=explanations(r,D('.3'),'total')
        def evaluate(node):
            if isinstance(node,ast.Expression):return evaluate(node.body)
            if isinstance(node,ast.Constant):return D(str(node.value))
            if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.USub):return -evaluate(node.operand)
            a,b=evaluate(node.left),evaluate(node.right)
            if isinstance(node.op,ast.Add):return a+b
            if isinstance(node.op,ast.Sub):return a-b
            if isinstance(node.op,ast.Mult):return a*b
            if isinstance(node.op,ast.Div):return a/b
            raise AssertionError('Operación inesperada')
        for row in r['rows']:
            with self.subTest(key=row['key']):
                expression=trace[row['key']]['expression'].replace(',','').replace('−','-').replace('×','*')
                result=evaluate(ast.parse(expression,mode='eval'))
                expected=D(str(fixture['expected'][row['key']]))*(100 if row['unit']=='%' else 1)
                self.assertLess(abs(result-expected),D('.000001'))

    def test_escenario_cero_en_todas_las_empresas_y_periodos(self):
        companies=dataset()['companies']
        for company in companies:
            for period in company['periods']:
                with self.subTest(ticker=company['ticker'],year=period['year']):
                    report=comparison(companies,company['ticker'],'NVDA',period['year'])
                    for card in simulate(report,changes({}),D('.3'),'total')['cards']:
                        self.assertEqual(card['before'],card['after'])

    def test_capital_trabajo_eur_tiene_conversion_en_traza(self):
        r=comparison(dataset()['companies'],'ASML');d=explanations(r,D('.3'),'total')
        self.assertIn('EUR/USD',d['working_capital']['expression'])
        self.assertEqual(d['working_capital']['value'],r['rows'][1]['own'])

    def test_moneda_sin_conversion_no_afirma_valor_comparable(self):
        r=example();c=deepcopy(r['selected']['company']);c['periods'][0]['currency']='PEN'
        r=comparison([c],'TEST','TEST');d=explanations(r,D('.3'),'total')
        self.assertEqual(d['working_capital']['value'],'N/D')
        self.assertIn('conversión',d['working_capital']['reason'])

    def test_tutor_muestra_referente_roe_y_dupont_calculados(self):
        r=comparison(dataset()['companies']);d=explanations(r,D('.3'),'total')
        answer,metric=tutor(r,d,'¿Por qué mi ROE difiere del referente?')
        self.assertEqual(metric,'roe');self.assertIn('31.05%',answer);self.assertIn('119.18%',answer)
        self.assertIn('DuPont',answer);self.assertIn('separado del caso',answer)
        follow,key=tutor(r,d,'¿Y frente al líder?','roe');self.assertEqual(key,'roe')
        self.assertIn('NVDA',follow)

    def test_firma_cambia_al_editar_importes_y_configuracion(self):
        c=dataset()['companies'];stamp=version(c,{'year':2025})
        other=deepcopy(c);other[0]['periods'][0]['values']['revenue']='1'
        self.assertNotEqual(stamp,version(other,{'year':2025}))
        self.assertNotEqual(stamp,version(c,{'year':2024}))


@override_settings(WORKSPACE_ISOLATION=True)
class RatioLabHttpTests(TestCase):
    def setUp(self): cache.clear();self.a=Client();self.b=Client()

    def params(self,client=None):
        r=(client or self.a).get('/ratios-financieros/');self.assertEqual(r.status_code,200)
        config=dict(r.context['ratio_lab_context']);config['deuda_base']=config.pop('deuda')
        return config

    def test_simula_anonimo_sin_modificar_fuentes_ni_caso(self):
        params=self.params();params.update(ventas='10',costos='0',deuda='-20')
        before=self.a.get('/casos-anteriores/actual/').json()
        r=self.a.post('/ratios-financieros/laboratorio/',params)
        self.assertEqual(r.status_code,200,r.content);self.assertEqual(len(r.json()['cards']),8)
        self.assertIn('SIMULACIÓN',r.json()['label'])
        self.assertEqual(self.a.get('/casos-anteriores/actual/').json(),before)
        with acceso_administrativo():self.assertEqual(FinancialRatioPeriod.objects.count(),0)
        self.assertEqual(self.b.get('/casos-anteriores/actual/').json()['asientos'],[])

    def test_chat_financiero_no_requiere_groq_y_voz_conserva_formato(self):
        params=self.params();params.update(context='ratios_externos',message='Explícame el ROE')
        with patch('core.views.Groq') as api:
            r=self.a.post('/chatbot/',params)
        self.assertEqual(r.status_code,200,r.content);api.assert_not_called()
        self.assertEqual(r.json()['status'],'calculated');self.assertIsInstance(r.json()['segments'],list)
        self.assertIn('AVGO',r.json()['response']);self.assertIn('31.05%',r.json()['response'])

    def test_chat_comenta_escenario_identificando_variaciones(self):
        params=self.params();params.update(context='ratios_externos',message='Explica mi escenario simulado',ventas='10',costos='5',deuda='0')
        r=self.a.post('/chatbot/',params)
        self.assertEqual(r.status_code,200);self.assertIn('SIMULACIÓN',r.json()['response'])
        self.assertIn('ventas 10%',r.json()['response'])

    def test_post_requiere_csrf_y_get_no_ejecuta(self):
        strict=Client(enforce_csrf_checks=True);p=self.params(strict)
        self.assertEqual(strict.post('/ratios-financieros/laboratorio/',p).status_code,403)
        self.assertEqual(self.a.get('/ratios-financieros/laboratorio/').status_code,405)
        r=strict.post('/ratios-financieros/laboratorio/',p,HTTP_X_CSRFTOKEN=strict.cookies['csrftoken'].value)
        self.assertEqual(r.status_code,200,r.content)

    def test_datos_modificados_entre_peticiones_se_rechazan(self):
        p=self.params();p['version']='antigua'
        self.assertEqual(self.a.post('/ratios-financieros/laboratorio/',p).status_code,409)
        p.update(context='ratios_externos',message='ROE')
        self.assertEqual(self.a.post('/chatbot/',p).status_code,409)

    def test_edicion_durante_calculo_no_devuelve_respuesta_antigua(self):
        p=self.params();before=dataset()['companies'];after=deepcopy(before)
        after[0]['periods'][0]['values']['revenue']='1'
        with patch('core.ratio_views.companies_with_overrides',side_effect=[({},before),({},after)]):
            r=self.a.post('/ratios-financieros/laboratorio/',p)
        self.assertEqual(r.status_code,409)
        self.assertIn('durante',r.json()['error'])

    def test_parametros_falsificados_y_tamano_se_rechazan(self):
        p=self.params()
        for field,value in [('ventas','NaN'),('year','x'),('tasa','Infinity'),('deuda_base','otros'),('action','borrar')]:
            with self.subTest(field=field):
                data={**p,field:value};self.assertEqual(self.a.post('/ratios-financieros/laboratorio/',data).status_code,400)
        r=self.a.post('/chatbot/',{**p,'context':'ratios_externos','message':'a'*4001})
        self.assertEqual(r.status_code,400)

    def test_csv_original_no_cambia_tras_simular(self):
        p=self.params();before=self.a.get('/ratios-financieros/?descargar=csv').content
        self.a.post('/ratios-financieros/laboratorio/',{**p,'ventas':'50','deuda':'50'})
        self.assertEqual(self.a.get('/ratios-financieros/?descargar=csv').content,before)

    def test_ambito_contable_conserva_respuesta_original(self):
        self.params()
        r=self.a.post('/chatbot/',{'message':'Dime la utilidad neta','context':'caso'})
        self.assertEqual(r.status_code,200);self.assertIn('No hay asientos',r.json()['response'])

    def test_aislamiento_de_datos_manuales_entre_visitantes(self):
        pa=self.params();pb=self.params(self.b);workspace=self.a.session['workspace_id']
        with acceso_administrativo():
            FinancialRatioPeriod.objects.create(workspace_id=workspace,ticker='AVGO',year=2025,name='Empresa propia',currency='USD',
              period_start='2025-01-01',period_end='2025-12-31',previous_end='2024-12-31',values={'net_income':'1','revenue':'10','equity':'5','equity_previous':'5'})
        self.assertEqual(self.a.post('/ratios-financieros/laboratorio/',pa).status_code,409)
        self.assertEqual(self.b.post('/ratios-financieros/laboratorio/',pb).status_code,200)
        fresh=self.params();r=self.a.post('/chatbot/',{**fresh,'context':'ratios_externos','message':'Explica margen neto'})
        self.assertIn('10.00%',r.json()['response'])
        other=self.b.post('/chatbot/',{**pb,'context':'ratios_externos','message':'Explica margen neto'})
        self.assertIn('36.20%',other.json()['response'])
