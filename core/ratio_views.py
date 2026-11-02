"""Ratios y edición de partidas independientes de los asientos contables."""
import csv
from decimal import Decimal
from io import StringIO
from urllib.parse import urlencode
from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from .models import FinancialRatioPeriod
from .ratios import FIELDS, comparison, companies_with_overrides, FX_SOURCE, fmt


class FinancialInputsForm(forms.Form):
    ticker = forms.RegexField(r'^[A-Z0-9][A-Z0-9.-]{0,11}$', max_length=12, label='Ticker')
    name = forms.CharField(max_length=120, label='Empresa')
    industry = forms.CharField(max_length=160, required=False, label='Actividad')
    year = forms.IntegerField(min_value=2000, max_value=2100, label='Ejercicio fiscal')
    currency = forms.ChoiceField(choices=[('USD','USD'),('EUR','EUR'),('PEN','PEN')], label='Moneda')
    period_start = forms.DateField(widget=forms.DateInput(format='%Y-%m-%d', attrs={'type':'date'}), label='Inicio del ejercicio')
    period_end = forms.DateField(widget=forms.DateInput(format='%Y-%m-%d', attrs={'type':'date'}), label='Cierre del ejercicio')
    previous_end = forms.DateField(widget=forms.DateInput(format='%Y-%m-%d', attrs={'type':'date'}), label='Cierre anterior')
    source_url = forms.URLField(max_length=600, required=False, label='Fuente (URL)', assume_scheme='https')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        signed = {'equity','equity_previous','total_equity','operating_income','net_income'}
        for key, label in FIELDS.items():
            self.fields[key] = forms.DecimalField(label=label, required=False, max_digits=24, decimal_places=8,
                min_value=None if key in signed else 0,
                widget=forms.NumberInput(attrs={'step':'any', 'placeholder':'Sin dato'}))

    def clean(self):
        data = super().clean()
        start,end,previous = (data.get(k) for k in ('period_start','period_end','previous_end'))
        if start and end and not 300 <= (end-start).days <= 380:
            self.add_error('period_end','Use un ejercicio anual de entre 301 y 381 días inclusive.')
        if previous and start and previous >= start:
            self.add_error('previous_end','El cierre anterior debe preceder al inicio del ejercicio.')
        if previous and end and not 300 <= (end-previous).days <= 400:
            self.add_error('previous_end','Use el cierre del ejercicio inmediatamente anterior.')
        if end and data.get('year') and abs(end.year-data['year']) > 1:
            self.add_error('year','El ejercicio no corresponde al año del cierre.')
        a,l,e = (data.get(k) for k in ('assets','liabilities','total_equity'))
        if all(v is not None for v in (a,l,e)) and abs(a-l-e)>Decimal('.01'):
            self.add_error('total_equity','Activo debe coincidir con pasivo + patrimonio consolidado (tolerancia 0.01 millones).')
        return data


def safe_csv(value):
    text = str(value)
    return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text


def financial_ratios(request):
    data, companies = companies_with_overrides()
    available = {c['ticker'] for c in companies}
    ticker = request.GET.get('empresa','AVGO')
    leader = request.GET.get('lider','NVDA')
    group = request.GET.get('grupo','all')
    basis = request.GET.get('deuda','total')
    group = group if group in ('all','chips','equipment') else 'all'
    basis = basis if basis in ('total','current') else 'total'
    try:
        year = int(request.GET.get('year','2025'))
        tax = Decimal(request.GET.get('tasa','30'))
        if not tax.is_finite() or not 0 <= tax <= 100:
            raise ValueError
    except (ValueError, ArithmeticError):
        year,tax = 2025,Decimal('30')
        messages.error(request,'Revise el año y la tasa: se muestran FY2025 y 30%.')
    ticker = ticker if ticker in available else 'AVGO'
    leader = leader if leader in available else 'NVDA'
    years = sorted({p['year'] for c in companies for p in c['periods']}, reverse=True)
    form = None
    if request.method == 'POST':
        form = FinancialInputsForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            defaults = {k: cleaned[k] for k in ('name','industry','currency','period_start','period_end','previous_end','source_url')}
            defaults['values'] = {k: str(cleaned[k]) if cleaned.get(k) is not None else None for k in FIELDS}
            with transaction.atomic():
                FinancialRatioPeriod.objects.update_or_create(ticker=cleaned['ticker'],year=cleaned['year'],defaults=defaults)
            messages.success(request,'Datos guardados y ratios recalculados. Los asientos contables se conservan.')
            return redirect(reverse('ratios_financieros')+'?'+urlencode({'empresa':cleaned['ticker'],'year':cleaned['year'],'lider':leader,'deuda':basis,'tasa':str(tax),'grupo':group})+'#comparativo')
        messages.error(request,'Revise los campos señalados. No se guardó ningún cambio.')
    try:
        report = comparison(companies,ticker,leader,year,tax/100,basis,group)
    except ValueError:
        ticker,year = 'AVGO',2025
        report = comparison(companies,ticker,leader,year,tax/100,basis,group)
        messages.error(request,'No hay datos para esa combinación. Se muestra Broadcom FY2025.')
    period, company = report['selected']['period'], report['selected']['company']
    if form is None:
        initial = {**period['values'],'ticker':ticker,'name':company['name'],'industry':company['industry'],
            'year':year,'currency':period['currency'],'period_start':period['start'],'period_end':period['end'],
            'previous_end':period.get('previous_end',f'{year-1}-12-31'),
            'source_url':period.get('manual_source') or period['provenance'].get('revenue',{}).get('url','')}
        form = FinancialInputsForm(initial=initial)
    input_rows = []
    for key, label in FIELDS.items():
        source = period['provenance'].get(key,{})
        input_rows.append({'key':key,'label':label,'field':form[key],
            'value':fmt(report['selected']['inputs'][key],'money'),'source':source.get('url',''),
            'tag':source.get('tag',''),'note':source.get('note',''),'end':source.get('end','')})
    query = urlencode({'empresa':ticker,'lider':leader,'year':year,'tasa':str(tax),'deuda':basis,'grupo':group})
    context = {**report,'company':company,'period':period,'ticker':ticker,'leader':leader,'year':year,
        'companies':companies,'years':years,'group':group,'debt_basis':basis,'tax_rate':str(tax),
        'as_of':data['as_of'],'form':form,'input_rows':input_rows,'fx_source':FX_SOURCE,'export_query':query,
        'metadata_fields':[form[k] for k in ('ticker','name','industry','year','currency','period_start','period_end','previous_end','source_url')],
        'categories':['Liquidez','Solvencia','Gestión','Rentabilidad'],
        'peer_periods':[{'company':c,'period':p} for c in companies for p in c['periods'] if p['year']==year],
        'ebitda':fmt(report['selected']['ebitda'],'money')}
    if request.GET.get('descargar') == 'csv':
        stream = StringIO()
        writer = csv.writer(stream)
        writer.writerow(['BROADBROS','Ratios financieros',ticker,year,period['start'],period['end']])
        writer.writerow(['Método','Promedio simple del grupo académico; n disponible por indicador.','Tasa ROA',str(tax)+'%','Base deuda',basis])
        writer.writerow(['Indicador','Unidad',str(year-1),ticker,leader,'Promedio grupo','n','Fórmula','Observación'])
        for row in report['rows']:
            writer.writerow([safe_csv(row[k]) for k in ('label','unit','previous','own','leader','sector','n','formula','reason')])
        writer.writerow(['Fuentes y cierres'])
        for c in companies:
            for p in c['periods']:
                if p['year']==year:
                    writer.writerow([safe_csv(c['ticker']),p['start'],p['end'],p['currency'],safe_csv(c.get('source_url',''))])
        writer.writerow(['Método y supuestos'])
        for note in report['selected']['assumptions']:
            writer.writerow(['Supuesto', safe_csv(note)])
        writer.writerow(['ROA', 'Tasa académica de referencia; no es la tasa efectiva de la compañía.'])
        writer.writerow(['EBITDA', 'Utilidad operativa + D&A; no es EBITDA ajustado.'])
        net_source = period['provenance'].get('net_income', {})
        if net_source.get('verified'):
            writer.writerow(['Verificación de utilidad', safe_csv(net_source['url']), safe_csv(net_source['note'])])
        return HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8',
            headers={'Content-Disposition':f'attachment; filename="Ratios_{ticker}_{year}.csv"'})
    return render(request,'ratios_financieros.html',context)


def ratios_caso(request):
    from .ratios_caso import calcular_caso
    reporte = calcular_caso()
    if request.GET.get('descargar') == 'csv':
        stream = StringIO()
        writer = csv.writer(stream)
        writer.writerow(['BROADBROS', 'Caso activo', 'Moneda PEN', 'Sin aproximaciones académicas'])
        writer.writerow(['Indicador', 'Fórmula', 'Valor', 'Dato pendiente'])
        for r in reporte['filas']:
            writer.writerow([safe_csv(r[k]) for k in ('nombre', 'formula', 'valor', 'motivo')])
        return HttpResponse('\ufeff'+stream.getvalue(), content_type='text/csv; charset=utf-8',
                            headers={'Content-Disposition': 'attachment; filename=Ratios_caso_BROADBROS.csv'})
    return render(request, 'ratios_caso.html', reporte)
