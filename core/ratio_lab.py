"""Laboratorio académico: trazas y escenarios sin escrituras ni cálculo en JS."""
from copy import deepcopy
from decimal import Decimal as D
from hashlib import sha256
import json
import re
from .ratios import FIELDS, DEFINITIONS, FX, calculate, fmt, number
from .validacion_contable import texto

SCENARIO_KEYS = ('gross_margin', 'operating_margin', 'net_margin', 'ebitda_margin', 'roa', 'roe', 'interest_cover', 'debt_cover')
MEANING = {
 'current':'Cuántas veces el activo corriente cubre el pasivo corriente; no garantiza pagos futuros.',
 'working_capital':'Diferencia entre recursos y obligaciones corrientes. Depende del tamaño de la empresa.',
 'quick':'Cobertura corriente con caja y clientes, usando la fórmula del taller.',
 'leverage':'Pasivo total por cada unidad de patrimonio consolidado; no equivale solo a deuda bancaria.',
 'debt_ratio':'Qué proporción del activo está financiada por pasivos.',
 'interest_cover':'Cuántas veces el EBITDA cubre los intereses. EBITDA no equivale a caja disponible.',
 'debt_cover':'Deuda financiera por unidad de EBITDA. No incluye otros pasivos no financieros.',
 'inventory_days':'Días de inventario a partir del saldo promedio; no es la edad de cada producto.',
 'receivable_days':'Plazo medio aproximado de cobro; usa ventas totales si no se conocen las ventas al crédito.',
 'payable_days':'Plazo medio aproximado de pago; más días no implican mejores condiciones.',
 'cash_cycle':'Tiempo aproximado entre pagar las compras y cobrar las ventas; puede ser negativo.',
 'gross_margin':'Parte de las ventas que queda después del costo de ventas, antes de otros gastos.',
 'operating_margin':'Resultado operativo por cada unidad vendida, antes del resultado financiero e impuestos.',
 'net_margin':'Utilidad atribuible al accionista por cada unidad de ventas; conserva pérdidas reales.',
 'ebitda_margin':'EBITDA sobre ventas: utilidad operativa más depreciación y amortización, sin ajustes adicionales.',
 'roa':'Rendimiento operativo del activo promedio con la tasa académica elegida, no la tasa efectiva de la compañía.',
 'roe':'Utilidad atribuible al accionista sobre su patrimonio promedio. Un ROE alto también puede acompañar mayor apalancamiento.',
}


def version(companies, config):
    payload = json.dumps([companies, config], sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':'))
    return sha256(payload.encode()).hexdigest()


def amount(value):
    return 'N/D' if value is None else f'{value:,.8f}'.rstrip('0').rstrip('.')


def explanations(report, tax, basis):
    v = report['selected']['inputs']
    def x(k): return amount(v.get(k))
    def avg(k): return f'(({x(k+"_previous")} + {x(k)}) / 2)'
    ebitda = f'({x("operating_income")} + {x("da")})'
    credit = 'credit_revenue' if v['credit_revenue'] is not None else 'revenue'
    purchase = 'credit_purchases' if v['credit_purchases'] is not None else 'cost_sales'
    expressions = {
      'current':f'{x("current_assets")} / {x("current_liabilities")}',
      'working_capital':f'{x("current_assets")} − {x("current_liabilities")}',
      'quick':f'({x("cash")} + {x("receivables")}) / {x("current_liabilities")}',
      'leverage':f'{x("liabilities")} / {x("total_equity")}',
      'debt_ratio':f'({x("liabilities")} / {x("assets")}) × 100',
      'interest_cover':f'{ebitda} / {x("interest")}',
      'debt_cover':f'({x("debt_current")}'+(f' + {x("debt_noncurrent")}' if basis=='total' else '')+f') / {ebitda}',
      'inventory_days':f'{avg("inventory")} × 365 / {x("cost_sales")}',
      'receivable_days':f'{avg("receivables")} × 365 / {x(credit)}',
      'payable_days':f'{avg("payables")} × 365 / {x(purchase)}',
      'cash_cycle':' + '.join([amount(report['selected']['values']['inventory_days']),amount(report['selected']['values']['receivable_days'])])+' − '+amount(report['selected']['values']['payable_days']),
      'gross_margin':f'(({x("revenue")} − {x("cost_sales")}) / {x("revenue")}) × 100',
      'operating_margin':f'({x("operating_income")} / {x("revenue")}) × 100',
      'net_margin':f'({x("net_income")} / {x("revenue")}) × 100',
      'ebitda_margin':f'({ebitda} / {x("revenue")}) × 100',
      'roa':f'({x("operating_income")} × (1 − {amount(tax)} ) / {avg("assets")}) × 100',
      'roe':f'({x("net_income")} / {avg("equity")}) × 100',
    }
    deps = {
      'current':['current_assets','current_liabilities'], 'working_capital':['current_assets','current_liabilities'],
      'quick':['cash','receivables','current_liabilities'], 'leverage':['liabilities','total_equity'],
      'debt_ratio':['liabilities','assets'], 'interest_cover':['operating_income','da','interest'],
      'debt_cover':['debt_current']+(['debt_noncurrent'] if basis=='total' else [])+['operating_income','da'],
      'inventory_days':['inventory_previous','inventory','cost_sales'],
      'receivable_days':['receivables_previous','receivables',credit],
      'payable_days':['payables_previous','payables',purchase],
      'cash_cycle':['inventory_previous','inventory','cost_sales','receivables_previous','receivables',credit,'payables_previous','payables',purchase],
      'gross_margin':['revenue','cost_sales'], 'operating_margin':['operating_income','revenue'],
      'net_margin':['net_income','revenue'], 'ebitda_margin':['operating_income','da','revenue'],
      'roa':['operating_income','assets_previous','assets'], 'roe':['net_income','equity_previous','equity'],
    }
    period = report['selected']['period']
    result = {}
    for row in report['rows']:
        key=row['key']; expression=expressions[key]
        notes=[]
        if key in ('receivable_days','cash_cycle') and credit=='revenue': notes.append('Ventas totales como aproximación de ventas al crédito.')
        if key in ('payable_days','cash_cycle') and purchase=='cost_sales': notes.append('Costo de ventas como aproximación de compras al crédito.')
        if key=='roa': notes.append(f'Tasa académica: {amount(tax*100)}%; no es la tasa efectiva publicada.')
        if key=='working_capital' and period['currency']!='USD':
            rate=FX.get(period['year']) if period['currency']=='EUR' else None
            expression=f'({expression}) × {amount(rate)} EUR/USD' if rate is not None else expression+'; falta conversión a USD'
            notes.append('La tabla compara capital de trabajo en USD millones; las partidas originales conservan su moneda.')
        sources=[]
        for field in dict.fromkeys(deps[key]):
            source=period.get('provenance',{}).get(field,{})
            sources.append({'label':FIELDS[field], 'value':x(field), 'url':period.get('manual_source','') if period.get('edited') else source.get('url',''),
                'origin':'Dato no disponible' if v[field] is None else 'Dato manual' if period.get('edited') else 'Partida del conjunto publicado'})
        result[key]={'key':key,'label':row['label'],'formula':row['formula'],'expression':expression,'value':row['own'],
            'meaning':MEANING[key], 'reason':row['reason'],'notes':notes,'inputs':sources,
            'currency':period['currency'],'leader':row['leader'],'sector':row['sector'],'n':row['n']}
    return result


def changes(post):
    result={}
    for k in ('ventas','costos','deuda'):
        value=number(post.get(k,'0'))
        if value is None or not -50<=value<=50: raise ValueError('Cada variación debe estar entre −50% y +50%.')
        if value.as_tuple().exponent < -2: raise ValueError('Usa hasta dos decimales en las variaciones.')
        result[k]=value
    return result


def simulate(report, change, tax, basis):
    original=report['selected']['inputs']; v=deepcopy(original)
    for field,control in [('revenue','ventas'),('credit_revenue','ventas'),('cost_sales','costos'),('credit_purchases','costos'),('debt_current','deuda'),('debt_noncurrent','deuda')]:
        if v[field] is not None: v[field]=v[field]*(1+change[control]/100)
    delta=None
    if all(original[k] is not None for k in ('revenue','cost_sales','operating_income')):
        delta=(v['revenue']-original['revenue'])-(v['cost_sales']-original['cost_sales'])
        v['operating_income']=original['operating_income']+delta
    elif change['ventas'] or change['costos']:
        v['operating_income']=None
    if original['net_income'] is not None and delta is not None:
        v['net_income']=original['net_income']+delta*(1-tax)
    elif change['ventas'] or change['costos']:
        v['net_income']=None
    calculated=calculate(v,tax,basis)
    cards=[]
    for key,label,category,unit,formula,direction in DEFINITIONS:
        if key not in SCENARIO_KEYS:continue
        before=report['selected']['values'][key]; after=calculated['values'][key]
        diff=after-before if before is not None and after is not None else None
        cards.append({'key':key,'label':label,'before':fmt(before,unit),'after':fmt(after,unit),
            'delta':'N/D' if diff is None else f'{diff*100:+,.2f} pp' if unit=='%' else f'{diff:+,.2f}x',
            'reason':calculated['reasons'].get(key,'')})
    return {'cards':cards,'changes':{k:str(v) for k,v in change.items()},'inputs':{FIELDS[k]:amount(v[k]) for k in ('revenue','cost_sales','operating_income','net_income','debt_current','debt_noncurrent')},
        'label':'SIMULACIÓN ACADÉMICA · no modifica datos publicados ni el caso contable',
        'assumptions':f'Se mantienen otros gastos operativos, D&A, intereses, activos y patrimonio promedio. La variación neta se aproxima como variación operativa × (1 − tasa académica de {amount(tax*100)}%), sin modelar la fiscalidad real. La deuda solo afecta la cobertura; no se reconstruyen los estados financieros ni los flujos de caja.'}


def tutor(report, details, message, previous_metric='', scenario=None):
    q=texto(message); selected=report['selected']; ref=report['reference']
    prefix=f"{selected['company']['name']} ({selected['company']['ticker']}), FY{selected['period']['year']}; análisis externo, separado del caso contable. "
    if re.search(r'\b(simulacion|simulado|escenario)\b',q) and scenario:
        cards={r['key']:r for r in scenario['cards']}
        answer=prefix+'SIMULACIÓN ACADÉMICA (variaciones: '+', '.join(k+' '+v+'%' for k,v in scenario['changes'].items())+'): margen neto '+cards['net_margin']['after']+', ROE '+cards['roe']['after']+' y deuda/EBITDA '+cards['debt_cover']['after']+'.\nEs un escenario con otros factores constantes; no modifica tus registros ni predice resultados reales.'
        if re.search(r'detalle|supuesto|paso a paso',q):answer+='\n'+scenario['assumptions']
        return answer, ''
    from .bot_ratios import indicador_consultado, quiere_detalle
    aliases={'roe':['roe','patrimonio del accionista'],'roa':['roa'],'current':['liquidez corriente','liquidez'],
       'quick':['prueba acida'],'working_capital':['capital de trabajo'],'leverage':['endeudamiento contable'],
       'debt_ratio':['porcentaje de endeudamiento'],'interest_cover':['cobertura de intereses'],
       'debt_cover':['deuda','cobertura de endeudamiento'],'inventory_days':['inventario'],
       'receivable_days':['cobrar','cxc'],'payable_days':['pagar','cxp'],'cash_cycle':['ciclo de efectivo'],
       'gross_margin':['margen bruto'],'operating_margin':['margen operativo'],'net_margin':['margen neto'],
       'ebitda_margin':['margen ebitda','ebitda']}
    metric=indicador_consultado(message) or next((k for k,terms in aliases.items() if any(re.search(r'\b'+re.escape(t)+r'\b',q) for t in terms)), '')
    if not metric and previous_metric in details and re.search(r'^(y\b|por que\b)|\b(ese|eso|anterior|referente|lider)\b',q):metric=previous_metric
    if metric:
        d=details[metric]; row=next(r for r in report['rows'] if r['key']==metric)
        if not quiere_detalle(message):
            short=f"{selected['company']['ticker']} · FY{selected['period']['year']} · análisis externo\n{d['label']}: {d['value']}. "
            short+=(d['reason']+' N/D no significa cero.') if d['value']=='N/D' else d['meaning']
            short+=f"\nReferente {ref['company']['ticker'] if ref else 'sin período'}: {row['leader']}; grupo: {row['sector']} (n={row['n']})."
            if d['notes']:short+=' '+ ' '.join(d['notes'])
            if metric=='roe' and ref and ('por que' in q or 'dupont' in q):
                short+='\nDuPont ayuda a revisar margen, rotación y apalancamiento; sus diferencias no prueban una causa empresarial.'
                short+=' Análisis separado del caso contable.'
            return short,metric
        response=prefix+f"{d['label']}: {d['value']}. Fórmula: {d['formula']}. Sustitución: {d['expression']}. "
        response+=d['reason'] if d['value']=='N/D' else d['meaning']
        response+='\n\nReferente '+(ref['company']['ticker'] if ref else 'sin período disponible')+': '+row['leader']+'; promedio del grupo: '+row['sector']+f" (n={row['n']}). "+' '.join(d['notes'])
        if metric=='roe' and ref:
            sv,rv=selected['values'],ref['values']
            response+=' DuPont (empresa / referente): margen '+fmt(sv['net_margin'],'%')+' / '+fmt(rv['net_margin'],'%')+', rotación '+fmt(sv['_turnover'])+' / '+fmt(rv['_turnover'])+', multiplicador '+fmt(sv['_multiplier'])+' / '+fmt(rv['_multiplier'])+'. Son componentes de una identidad contable, no prueba de una causa operativa.'
        return response,metric
    if 'dupont' in q:
        if not report['dupont']['matches']:
            return prefix+'DuPont no es evaluable con estos datos: revisa la utilidad neta, las ventas y los saldos de activo y patrimonio promedio. Un dato desconocido o denominador no válido permanece como N/D.', 'roe'
        return prefix+'ROE = margen neto × rotación de activos × multiplicador del patrimonio. '+report['dupont']['margin']+' × '+report['dupont']['turnover']+' × '+report['dupont']['multiplier']+' ≈ '+report['dupont']['roe']+'. Se usan valores sin redondear para conciliar; las cifras visibles están redondeadas.', 'roe'
    if any(k in q for k in ('fuente','dato','n/d','supuesto')):
        return prefix+'Pulsa cualquier indicador para ver su cálculo, partidas, fuente y aproximaciones. Los datos ausentes o denominadores no interpretables quedan como N/D; no se sustituyen por cero. Los cierres fiscales pueden diferir entre empresas; el promedio corresponde al grupo académico y no a un índice oficial del sector.', ''
    if any(k in q for k in ('resumen','rentable','solvente','diagnostico','sustentar','exponer')):
        rows={r['key']:r for r in report['rows']}
        return prefix+'\n'+ '\n'.join(f"• {rows[k]['label']}: {rows[k]['own']}." for k in ('current','debt_ratio','net_margin'))+'\nOrientan sobre liquidez, financiación y rentabilidad; no bastan para asegurar solvencia futura. Pregúntame por uno para interpretarlo.', ''
    return prefix+'Puedo explicar los 17 ratios con sus datos reales. Prueba «Explícame el margen neto» o «¿Qué significa N/D?». Para ver las operaciones, pide «el cálculo paso a paso».', ''
