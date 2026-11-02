"""17 indicadores del taller UNI: cálculos decimales, trazabilidad y pares."""
import json
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

D = Decimal
FIELDS = {
    'current_assets': 'Activo corriente', 'current_liabilities': 'Pasivo corriente',
    'cash': 'Caja y equivalentes', 'receivables': 'Cuentas por cobrar comerciales',
    'receivables_previous': 'CxC al cierre anterior', 'inventory': 'Inventario',
    'inventory_previous': 'Inventario al cierre anterior', 'payables': 'Cuentas por pagar comerciales',
    'payables_previous': 'CxP al cierre anterior', 'assets': 'Activo total',
    'assets_previous': 'Activo total al cierre anterior', 'liabilities': 'Pasivo total',
    'equity': 'Patrimonio atribuible al accionista', 'equity_previous': 'Patrimonio del accionista al cierre anterior',
    'total_equity': 'Patrimonio consolidado total', 'debt_current': 'Deuda financiera CP',
    'debt_noncurrent': 'Deuda financiera LP', 'revenue': 'Ventas netas', 'cost_sales': 'Costo de ventas',
    'operating_income': 'Utilidad operativa', 'net_income': 'Utilidad neta atribuible al accionista',
    'interest': 'Gastos por intereses', 'da': 'Depreciación y amortización total',
    'credit_revenue': 'Ventas al crédito (opcional)', 'credit_purchases': 'Compras al crédito (opcional)',
}
DEFINITIONS = [
    ('current', 'Liquidez corriente', 'Liquidez', 'veces', 'AC / PC', 'high'),
    ('working_capital', 'Capital de trabajo neto', 'Liquidez', 'money', 'AC − PC', 'context'),
    ('quick', 'Prueba ácida', 'Liquidez', 'veces', '(Caja + CxC comerciales) / PC', 'high'),
    ('leverage', 'Endeudamiento contable', 'Solvencia', 'veces', 'Pasivo total / Patrimonio consolidado', 'low'),
    ('debt_ratio', 'Porcentaje de endeudamiento', 'Solvencia', '%', 'Pasivo total / Activo total', 'low'),
    ('interest_cover', 'Cobertura de intereses', 'Solvencia', 'veces', 'EBITDA / Intereses', 'high'),
    ('debt_cover', 'Cobertura de endeudamiento', 'Solvencia', 'veces', 'Deuda financiera (CP + LP) / EBITDA', 'low'),
    ('inventory_days', 'Días de inventario', 'Gestión', 'días', 'Inventario promedio × 365 / Costo de ventas', 'low'),
    ('receivable_days', 'Días de cuentas por cobrar', 'Gestión', 'días', 'CxC promedio × 365 / Ventas al crédito', 'low'),
    ('payable_days', 'Días de cuentas por pagar', 'Gestión', 'días', 'CxP promedio × 365 / Compras al crédito', 'context'),
    ('cash_cycle', 'Ciclo de efectivo', 'Gestión', 'días', 'Días de inventario + Días CxC − Días CxP', 'low'),
    ('gross_margin', 'Margen bruto', 'Rentabilidad', '%', '(Ventas − Costo de ventas) / Ventas', 'high'),
    ('operating_margin', 'Margen operativo', 'Rentabilidad', '%', 'Utilidad operativa / Ventas', 'high'),
    ('net_margin', 'Margen neto', 'Rentabilidad', '%', 'Utilidad neta / Ventas', 'high'),
    ('ebitda_margin', 'Margen EBITDA', 'Rentabilidad', '%', '(Utilidad operativa + D&A) / Ventas', 'high'),
    ('roa', 'ROA operativo después de impuestos', 'Rentabilidad', '%', 'Utilidad operativa × (1 − t) / Activo promedio', 'high'),
    ('roe', 'ROE', 'Rentabilidad', '%', 'Utilidad neta / Patrimonio promedio del accionista', 'high'),
]
FX = {2024: D('1.0389'), 2025: D('1.1750')}
FX_SOURCE = 'https://www.ecb.europa.eu/press/annual-reports-financial-statements/annual/annual-accounts/html/ecb.annualaccounts2025~ba3b593c99.en.html'


def dataset():
    # El archivo forma parte de la versión: no se consulta una API al abrir la página.
    return json.loads((Path(__file__).parent / 'data/financial_ratios.json').read_text())


def number(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('El importe debe ser un número.')
    try:
        n = D(str(value))
        if not n.is_finite() or abs(n) > D('1000000000000') or (n and n.adjusted() < -12):
            raise ValueError('Importe fuera de rango.')
        return n
    except (InvalidOperation, TypeError):
        raise ValueError('Use un número decimal válido, sin separadores de miles.') from None


def calculate(values, tax_rate=D('0.30'), debt_basis='total', period_days=365, allow_approximations=True):
    v = {k: number(values.get(k)) for k in FIELDS}
    signed = {'equity','equity_previous','total_equity','operating_income','net_income'}
    for key, value in v.items():
        if key not in signed and value is not None and value < 0:
            v[key] = None
    tax_rate = number(tax_rate)
    if tax_rate is not None and not D('0') <= tax_rate <= D('1'):
        raise ValueError('La tasa debe estar entre 0 y 100%.')
    if debt_basis not in ('total', 'current'):
        raise ValueError('Base de deuda inválida.')
    result, reasons, assumptions = {}, {}, []

    def add(*keys):
        xs = [v.get(k) for k in keys]
        return sum(xs, D('0')) if all(x is not None for x in xs) else None

    def mean(key):
        n = add(key, key+'_previous')
        return n / 2 if n is not None else None

    def divide(key, numerator, denominator, positive=True):
        if numerator is None or denominator is None:
            result[key], reasons[key] = None, 'Faltan partidas para calcularlo; consulte Datos y fuentes.'
        elif denominator == 0:
            result[key], reasons[key] = None, 'Denominador cero: no se presenta como cero ni infinito.'
        elif positive and denominator < 0:
            result[key], reasons[key] = None, 'Denominador negativo: indicador no interpretable con esta fórmula.'
        else:
            with localcontext() as ctx:
                ctx.prec = 32
                result[key] = numerator / denominator

    ebitda = add('operating_income', 'da')
    divide('_inventory_turnover', v['cost_sales'], mean('inventory'))
    divide('current', v['current_assets'], v['current_liabilities'])
    result['working_capital'] = (v['current_assets'] - v['current_liabilities']
                                if v['current_assets'] is not None and v['current_liabilities'] is not None else None)
    divide('quick', add('cash', 'receivables'), v['current_liabilities'])
    divide('leverage', v['liabilities'], v['total_equity'])
    divide('debt_ratio', v['liabilities'], v['assets'])
    divide('interest_cover', ebitda, v['interest'])
    divide('debt_cover', add('debt_current', 'debt_noncurrent') if debt_basis == 'total' else v['debt_current'], ebitda)
    credit_sales = v['credit_revenue']
    if credit_sales is None and allow_approximations:
        credit_sales = v['revenue']
        assumptions.append('Días CxC: ventas totales como aproximación de ventas al crédito, según el Excel del taller.')
    purchases = v['credit_purchases']
    if purchases is None and allow_approximations:
        purchases = v['cost_sales']
        assumptions.append('Días CxP: costo de ventas como aproximación de compras al crédito, según el taller; no es una compra observada.')
    for key, base, den in [('inventory_days', 'inventory', v['cost_sales']),
                           ('receivable_days', 'receivables', credit_sales),
                           ('payable_days', 'payables', purchases)]:
        avg = mean(base)
        divide(key, avg * period_days if avg is not None and period_days is not None else None, den)
    days = [result[k] for k in ('inventory_days', 'receivable_days', 'payable_days')]
    result['cash_cycle'] = days[0] + days[1] - days[2] if all(x is not None for x in days) else None
    gross = v['revenue'] - v['cost_sales'] if v['revenue'] is not None and v['cost_sales'] is not None else None
    for key, n in [('gross_margin', gross), ('operating_margin', v['operating_income']),
                   ('net_margin', v['net_income']), ('ebitda_margin', ebitda)]:
        divide(key, n, v['revenue'])
    nopat = v['operating_income'] * (1-tax_rate) if v['operating_income'] is not None and tax_rate is not None else None
    divide('roa', nopat, mean('assets'))
    divide('roe', v['net_income'], mean('equity'))
    divide('_turnover', v['revenue'], mean('assets'))
    divide('_multiplier', mean('assets'), mean('equity'))
    factors = [result['net_margin'], result['_turnover'], result['_multiplier']]
    dupont = factors[0]*factors[1]*factors[2] if all(x is not None for x in factors) else None
    warnings = []
    if all(v[k] is not None for k in ('assets', 'liabilities', 'total_equity')):
        delta = v['assets']-v['liabilities']-v['total_equity']
        if abs(delta) > D('0.01'):
            warnings.append(f'Activo no coincide con pasivo + patrimonio consolidado: diferencia {delta:,.2f} millones.')
    return {'values': result, 'reasons': reasons, 'assumptions': assumptions, 'ebitda': ebitda,
            'dupont': dupont, 'warnings': warnings, 'inputs': v}


def fmt(value, unit='veces'):
    if value is None:
        return 'N/D'
    if unit == '%':
        return f'{value*100:,.2f}%'
    return f'{value:,.2f}' + ('x' if unit == 'veces' else ' d' if unit == 'días' else '')


def companies_with_overrides():
    from .models import FinancialRatioPeriod
    data = dataset()
    companies = {c['ticker']: c for c in data['companies']}
    for item in FinancialRatioPeriod.objects.all().order_by('ticker', 'year'):
        company = companies.setdefault(item.ticker, {'ticker': item.ticker, 'name': item.name,
                                      'industry': item.industry, 'source_url': '', 'periods': []})
        company['name'], company['industry'] = item.name, item.industry
        company['periods'] = [p for p in company['periods'] if p['year'] != item.year]
        company['periods'].append({'year': item.year, 'start': item.period_start.isoformat(),
            'end': item.period_end.isoformat(), 'currency': item.currency, 'values': item.values,
            'previous_end': item.previous_end.isoformat(),
            'provenance': {}, 'notes': ['Datos ingresados por el usuario. Fuente: '+(item.source_url or 'pendiente de documentar')],
            'manual_source': item.source_url, 'edited': True})
    return data, list(companies.values())


def comparison(companies, ticker='AVGO', leader='NVDA', year=2025, tax_rate=D('.30'), debt_basis='total', group='all'):
    evaluated = {}
    for company in companies:
        for p in company['periods']:
            evaluated[(company['ticker'], p['year'])] = {**calculate(p['values'], tax_rate, debt_basis),
                                                          'period': p, 'company': company}
    selected = evaluated.get((ticker, year))
    if selected is None:
        raise ValueError('No hay datos para esa empresa y ejercicio.')
    reference = evaluated.get((leader, year))
    previous = evaluated.get((ticker, year-1))
    group_tickers = {'chips': {'AVGO', 'NVDA', 'AMD', 'INTC'}, 'equipment': {'ASML', 'AMAT', 'LRCX', 'KLAC'}}
    peers = [v for (t,y),v in evaluated.items() if y == year and (group == 'all' or t in group_tickers.get(group,set()))]
    prior_peers = [v for (t,y),v in evaluated.items() if y == year-1 and (group == 'all' or t in group_tickers.get(group,set()))]

    def historical_value(entry, key, unit):
        if entry is None: return None
        value = entry['values'][key]
        if unit != 'money' or value is None or entry['period']['currency'] == 'USD': return value
        rate = FX.get(entry['period']['year']) if entry['period']['currency'] == 'EUR' else None
        return value*rate if rate is not None else None
    rows, chart = [], {}
    for i,(key, label, category, unit, formula, direction) in enumerate(DEFINITIONS,1):
        if key == 'debt_cover' and debt_basis == 'current':
            formula = 'Deuda financiera CP / EBITDA'
        own = selected['values'][key]
        lead = reference['values'][key] if reference else None
        historic = previous['values'][key] if previous else None
        points = []
        for p in peers:
            value = p['values'][key]
            if value is None:
                continue
            # Solo el capital de trabajo requiere convertir moneda para comparar.
            if unit == 'money' and p['period']['currency'] == 'EUR':
                rate = FX.get(year)
                value = value * rate if rate is not None else None
            elif unit == 'money' and p['period']['currency'] != 'USD':
                value = None
            if value is not None:
                points.append({'ticker': p['company']['ticker'], 'value': value, 'display': fmt(value,unit),
                               'end': p['period']['end']})
        sector = sum((p['value'] for p in points),D('0'))/len(points) if points else None
        comparable = own
        if unit == 'money' and selected['period']['currency'] != 'USD':
            rate = FX.get(year) if selected['period']['currency'] == 'EUR' else None
            comparable = own*rate if own is not None and rate is not None else None
        if unit == 'money' and reference and reference['period']['currency'] != 'USD':
            rate = FX.get(year) if reference['period']['currency'] == 'EUR' else None
            lead = lead*rate if lead is not None and rate is not None else None
        if unit == 'money' and previous and previous['period']['currency'] != 'USD':
            rate = FX.get(year-1) if previous['period']['currency'] == 'EUR' else None
            historic = historic*rate if historic is not None and rate is not None else None
        delta = comparable - historic if comparable is not None and historic is not None else None
        gap = comparable - sector if comparable is not None and sector is not None else None
        tone = 'neutral'
        if gap is not None and direction != 'context':
            tone = 'positive' if (gap >= 0 if direction == 'high' else gap <= 0) else 'attention'
        interpretation = ('Por encima' if gap is not None and gap>0 else 'Por debajo' if gap is not None and gap<0 else 'En línea')+' del promedio del grupo.' if gap is not None else 'Sin base comparable suficiente.'
        if key == 'working_capital':
            interpretation += ' Su tamaño depende de la escala del negocio.'
        if key == 'payable_days':
            interpretation += ' Más días no garantizan mejores condiciones de pago.'
        rows.append({'number': i, 'key': key, 'label': label, 'category': category, 'unit': 'USD MM' if unit=='money' else unit,
                     'formula': formula, 'own': fmt(comparable,unit), 'leader': fmt(lead,unit),
                     'previous': fmt(historic,unit), 'sector': fmt(sector,unit), 'n': len(points),
                     'delta': 'N/D' if delta is None else f'{delta*100:+,.2f} pp' if unit=='%' else f'{delta:+,.2f}',
                     'tone': tone, 'interpretation': interpretation,
                     'reason': ('Falta una conversión documentada a USD para comparar este importe.' if unit == 'money' and own is not None and comparable is None else selected['reasons'].get(key, 'Faltan partidas para calcularlo.' if own is None else ''))})
        chart[key] = {'label': label, 'unit': 'USD MM' if unit=='money' else unit, 'points': [
            {**p, 'value': float(p['value'])} for p in points],
            'benchmarks': [
                {'ticker':ticker, 'kind':'company', 'role':'Empresa', 'value':float(comparable) if comparable is not None else None, 'display':fmt(comparable,unit)},
                {'ticker':leader, 'kind':'leader', 'role':'Referente', 'value':float(lead) if lead is not None else None, 'display':fmt(lead,unit)},
                {'ticker':'Grupo', 'kind':'group', 'role':f'Promedio · n={len(points)}', 'value':float(sector) if sector is not None else None, 'display':fmt(sector,unit)},
            ]}
        historical_reference = evaluated.get((leader,year-1))
        prior_values = [historical_value(p,key,unit) for p in prior_peers]
        prior_values = [v for v in prior_values if v is not None]
        prior_sector = sum(prior_values,D('0'))/len(prior_values) if prior_values else None
        periods = []
        if previous is not None or historical_reference is not None or prior_peers:
            periods.append((year-1,historical_value(previous,key,unit),historical_value(historical_reference,key,unit),prior_sector,len(prior_values)))
        periods.append((year,comparable,lead,sector,len(points)))
        chart[key]['history'] = [{'year':y,'n':n,'series':[
            {'kind':kind,'value':float(value) if value is not None else None,'display':fmt(value,unit)}
            for kind,value in [('company',own_y),('leader',lead_y),('group',group_y)]]}
            for y,own_y,lead_y,group_y,n in periods]
    v = selected['values']
    ni = selected['inputs']['net_income']
    debt, interest = v['debt_cover'], v['interest_cover']
    solvency = ('Cobertura no evaluable' if debt is None or interest is None else
                'Cobertura de intereses insuficiente' if interest < 1 else
                'Revisar endeudamiento' if debt >= 3 else 'Indicadores de solvencia favorables')
    if debt_basis == 'current':
        solvency = 'Evaluación parcial: solo deuda CP'
    diagnoses = [
        {'title': 'Liquidez', 'status': 'Cobertura corriente' if v['current'] is not None and v['current']>=1 else 'Liquidez ajustada' if v['current'] is not None else 'Datos pendientes',
         'text': ('Faltan partidas o un denominador válido para evaluar la liquidez corriente.' if v['current'] is None else 'El activo corriente cubre '+fmt(v['current'])+' el pasivo corriente. Es una medida estática, no una garantía de pago.')},
        {'title': 'Solvencia', 'status': solvency,
         'text': 'Deuda / EBITDA: '+fmt(debt)+'; cobertura de intereses: '+fmt(interest)+'. Referencia orientativa del taller: deuda / EBITDA menor a 3x, sin garantía de pago.'},
        {'title': 'Rentabilidad', 'status': 'Datos pendientes' if ni is None else 'Utilidad positiva' if ni>0 else 'Pérdida contable' if ni<0 else 'Resultado neto cero',
         'text': 'Margen neto '+fmt(v['net_margin'],'%')+' y ROE '+fmt(v['roe'],'%')+'. Rentabilidad contable del ejercicio, no una recomendación de inversión.'},
    ]
    return {'selected': selected, 'reference': reference, 'previous': previous, 'rows': rows,
            'chart_data': chart, 'diagnoses': diagnoses, 'peer_count': len(peers),
            'dupont': {'margin': fmt(v['net_margin'],'%'), 'turnover': fmt(v['_turnover']),
                       'multiplier': fmt(v['_multiplier']), 'roe': fmt(selected['dupont'],'%'),
                       'matches': selected['dupont'] is not None and v['roe'] is not None and abs(selected['dupont']-v['roe'])<D('0.000000000001')}}
