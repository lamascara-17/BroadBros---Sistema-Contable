"""Construye datos auditables desde SEC Company Facts, sin cotizaciones ni TTM.

Uso: python scripts/build_financial_dataset.py /ruta/cache
La carpeta debe contener AVGO.json, NVDA.json, etc. descargados de los
endpoints públicos companyfacts de la SEC. No se incorporan credenciales.
"""
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

COMPANIES = {
    'AVGO': ('Broadcom', 1730168, 'Chips y software de infraestructura'),
    'NVDA': ('NVIDIA', 1045810, 'Diseño de chips y sistemas de IA'),
    'AMD': ('AMD', 2488, 'Diseño de CPU y GPU'),
    'ASML': ('ASML', 937966, 'Equipos de litografía'),
    'AMAT': ('Applied Materials', 6951, 'Equipos para semiconductores'),
    'LRCX': ('Lam Research', 707549, 'Equipos para semiconductores'),
    'INTC': ('Intel', 50863, 'Chips y fundición'),
    'CSCO': ('Cisco', 858877, 'Redes e infraestructura'),
    'KLAC': ('KLA Corporation', 319201, 'Control e inspección de semiconductores'),
}
TAGS = {
    'current_assets': ['AssetsCurrent'],
    'current_liabilities': ['LiabilitiesCurrent'],
    'cash': ['CashAndCashEquivalentsAtCarryingValue'],
    'receivables': ['AccountsReceivableNetCurrent', 'AccountsNotesAndOtherReceivablesNetCurrent', 'AccountsReceivableNet'],
    'inventory': ['InventoryNet'],
    'payables': ['AccountsPayableCurrent'],
    'assets': ['Assets'],
    'liabilities': ['Liabilities'],
    'equity': ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'],
    'total_equity': ['StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', 'StockholdersEquity'],
    'debt_current': ['DebtCurrent', 'LongTermDebtCurrent', 'ShortTermBorrowings'],
    'debt_noncurrent': ['LongTermDebtNoncurrent', 'LongTermDebtAndCapitalLeaseObligations'],
    'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'],
    'cost_sales': ['CostOfRevenue', 'CostOfGoodsAndServicesSold'],
    'operating_income': ['OperatingIncomeLoss'],
    'net_income': ['NetIncomeLoss'],
    'interest': ['InterestExpenseNonoperating', 'InterestExpense'],
    'da': ['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization'],
}
FLOWS = {'revenue', 'cost_sales', 'operating_income', 'net_income', 'interest', 'da'}
CUTOFF = '2026-11-02'
FIRST_YEAR = 2022
LAST_YEAR = date.fromisoformat(CUTOFF).year


def apply_verified_inputs(ticker, period):
    """Excepciones revisadas en el informe completo, acotadas a empresa/periodo/moneda."""
    path = Path(__file__).resolve().parents[1] / 'core/data/verified_financial_inputs.json'
    for item in json.loads(path.read_text()):
        if item['provenance']['filed'] > CUTOFF:
            continue
        if ticker != item['ticker'] or any(period[k] != item[k] for k in ('year','start','end','currency')):
            continue
        period['values'][item['field']] = item['value']
        period['provenance'][item['field']] = item['provenance'].copy()
    return period


def build(cache):
    companies = []
    for ticker, (name, cik, industry) in COMPANIES.items():
        raw = json.loads((cache / f'{ticker}.json').read_text())
        facts = raw['facts']['us-gaap']
        unit = 'EUR' if ticker == 'ASML' else 'USD'

        def candidates(tags, end=None, flow=False, fy=None):
            for tag in tags:
                vals = []
                for v in facts.get(tag, {}).get('units', {}).get(unit, []):
                    if v.get('form') not in ('10-K', '20-F', '10-K/A') or v.get('filed', '') > CUTOFF:
                        continue
                    if end is not None and v['end'] != end:
                        continue
                    if fy is not None and (v.get('fy') != fy or v.get('fp') != 'FY'):
                        continue
                    if flow:
                        if not v.get('start') or not 300 <= (date.fromisoformat(v['end']) - date.fromisoformat(v['start'])).days <= 380:
                            continue
                    elif v.get('start'):
                        continue
                    vals.append((tag, v))
                if vals:
                    return vals
            return []

        periods = []
        for year in range(FIRST_YEAR, LAST_YEAR + 1):
            anchors = candidates(TAGS['revenue'], flow=True, fy=year)
            if not anchors:
                print(ticker, year, 'sin informe anual publicado al corte')
                continue
            end = max(v['end'] for _, v in anchors)
            anchors = [v for _, v in anchors if v['end'] == end]
            anchor = min(anchors, key=lambda v: v['filed'])
            accn = anchor['accn']
            starts = candidates(TAGS['assets'])
            previous = max((v['end'] for _, v in starts if 300 < (date.fromisoformat(end)-date.fromisoformat(v['end'])).days < 400), default=None)
            values, provenance, notes = {}, {}, []

            def take(key, tags, day=end, flow=False):
                vals = candidates(tags, day, flow)
                if flow:
                    vals = [(tag, v) for tag, v in vals if v.get('start') == anchor['start']]
                if not vals:
                    values[key] = None
                    return
                tag, v = min(vals, key=lambda tv: (tv[1]['accn'] != accn, tv[1]['filed']))
                values[key] = str(Decimal(str(v['val'])) / Decimal('1000000'))
                provenance[key] = {'tag': tag, 'end': v['end'], 'start': v.get('start'),
                    'accession': v['accn'], 'filed': v['filed'], 'unit': unit,
                    'url': f"https://www.sec.gov/Archives/edgar/data/{cik}/{v['accn'].replace('-', '')}/{v['accn']}-index.html"}

            for key, tags in TAGS.items():
                take(key, tags, flow=key in FLOWS)
            for key in ('inventory', 'receivables', 'payables', 'assets', 'equity'):
                if previous is not None: take(key+'_previous', TAGS[key], day=previous)
                else: values[key+'_previous'] = None
            # Desgloses cuyo tag agregado no representa toda la D&A.
            if ticker in ('AVGO', 'INTC', 'AMD'):
                take('_depreciation', ['Depreciation'], flow=True)
                take('_amortization', ['AmortizationOfIntangibleAssets'], flow=True)
                if ticker == 'AMD':
                    take('_depreciation', ['OtherDepreciationAndAmortization'], flow=True)
                    take('_amortization', ['AdjustmentForAmortization'], flow=True)
                if values['_depreciation'] is not None and values['_amortization'] is not None:
                    values['da'] = str(Decimal(values['_depreciation'])+Decimal(values['_amortization']))
                    provenance['da'] = {'components': [provenance['_depreciation'], provenance['_amortization']],
                        'url': provenance['_amortization']['url'], 'note': 'Depreciación + amortización de intangibles; sin otros ajustes de EBITDA.'}
            if ticker == 'CSCO':
                # El agregado de CF incluye «and other»; no equivale a D&A.
                values['da'] = None
                provenance.pop('da', None)
                notes.append('D&A total pendiente de desglose: no se usa la partida «depreciation, amortization, and other» como si fuera D&A pura.')
            if ticker == 'AVGO' and values.get('da') is None:
                notes.append('D&A pura pendiente de conciliación: el flujo combina intangibles y derechos de uso. Los indicadores que requieren EBITDA permanecen N/D hasta verificar el desglose, sin tomar EBITDA ajustado.')
            if ticker == 'KLAC':
                take('debt_noncurrent', ['LongTermDebt'])
                take('_rd', ['ResearchAndDevelopmentExpense'], flow=True)
                take('_sga', ['SellingGeneralAndAdministrativeExpense'], flow=True)
                take('_impairment', ['GoodwillAndIntangibleAssetImpairment'], flow=True)
                keys = ('revenue', 'cost_sales', '_rd', '_sga', '_impairment')
                if all(values[k] is not None for k in keys):
                    values['operating_income'] = str(Decimal(values['revenue']) - sum(Decimal(values[k]) for k in keys[1:]))
                    provenance['operating_income'] = {'url': provenance['revenue']['url'],
                        'note': 'Ingresos − costo de ventas − I+D − administración y ventas − deterioro operativo de goodwill e intangibles. KLA no presenta un subtotal operativo separado.',
                        'components': {k: {'value': values[k], **provenance[k]} for k in keys}}
            if ticker == 'AMAT':
                take('_short_debt', ['ShortTermBorrowings'])
                if values['_short_debt'] is not None and values['debt_current'] is not None:
                    values['debt_current'] = str(Decimal(values['debt_current'])+Decimal(values['_short_debt']))
                    provenance['debt_current'] = {'components': [provenance['debt_current'], provenance['_short_debt']],
                        'url': provenance['_short_debt']['url'], 'note': 'Vencimientos de deuda LP + deuda CP independiente.'}
            if values['liabilities'] is None and values['assets'] is not None and values['total_equity'] is not None:
                values['liabilities'] = str(Decimal(values['assets'])-Decimal(values['total_equity']))
                provenance['liabilities'] = {'url': provenance['assets']['url'], 'note': 'Activo total menos patrimonio consolidado total (incluye no controladoras).'}
            values = {k: v for k, v in values.items() if not k.startswith('_')}
            provenance = {k: v for k, v in provenance.items() if not k.startswith('_')}
            periods.append(apply_verified_inputs(ticker, {'year': year, 'start': anchor['start'], 'end': end, 'previous_end': previous,
                'currency': unit, 'values': values, 'provenance': provenance, 'notes': notes}))
            print(ticker, year, end, 'missing:', [k for k,v in values.items() if v is None])
        companies.append({'ticker': ticker, 'name': name, 'cik': cik, 'industry': industry,
                          'source_url': f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010}.json', 'periods': periods})
    return {'as_of': CUTOFF, 'coverage_start': FIRST_YEAR, 'coverage_end': LAST_YEAR,
            'period_kind': 'annual', 'unit': 'millones de moneda de presentación', 'companies': companies,
            'methodology': f'17 indicadores según S7 Alicorp y PPT S3/S4. Ejercicios anuales desde FY{FIRST_YEAR} hasta FY{LAST_YEAR}, solo si fueron publicados al corte; cierres distintos visibles, sin TTM ni trimestres tratados como años. Grupo académico de nueve empresas, no índice oficial de todo el sector.'}


if __name__ == '__main__':
    target = Path(__file__).resolve().parents[1] / 'core/data/financial_ratios.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build(Path(sys.argv[1])), ensure_ascii=False, indent=2)+'\n')
