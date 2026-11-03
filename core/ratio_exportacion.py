"""Informes de ratios: mismos resultados decimales que pantalla, sin recalcular."""
from decimal import Decimal
from io import BytesIO
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

from .ratios import FIELDS, DEFINITIONS, fmt


TEAL = '07393C'
CYAN = '2C666E'
PALE = 'E9F5F5'
GREY = '53696D'


def comparativo(context):
    period = context['period']
    rows = [{**r, 'displays': [r[k] for k in ('previous', 'own', 'leader', 'sector')],
             'values': [r['numbers'][k] for k in ('previous', 'own', 'leader', 'sector')]}
            for r in context['rows']]
    sources = []
    for company in context['companies']:
        for p in company['periods']:
            if p['year'] not in (context['year'] - 1, context['year']):
                continue
            source = p.get('provenance', {}).get('revenue', {}).get('url') or p.get('provenance', {}).get('current_assets', {}).get('url') or company.get('source_url', '')
            sources.append([company['ticker'], str(p['year']), p['start'], p['end'], p['currency'],
                            p.get('manual_source', '') if p.get('edited') else source,
                            'Manual' if p.get('edited') else 'Publicado'])
    for fx in context.get('fx_rates', []):
        sources.append(['BCE', str(fx['year']), '', '', 'EUR/USD', fx['source'], 'Conversión'])
    inputs = []
    for key, label in FIELDS.items():
        provenance = period.get('provenance', {}).get(key, {})
        inputs.append([label, context['selected']['inputs'].get(key), period['currency'] + ' millones',
                       provenance.get('tag', ''), period.get('manual_source', '') if period.get('edited') else provenance.get('url', '')])
    return {'title': context['company']['name'], 'subtitle': f"Ratios financieros - {context['ticker']} / FY{context['year']}",
            'period': f"{period['start']} al {period['end']}", 'scope': 'Comparación externa - datos originales, sin escenarios simulados.',
            'headers': ['Indicador / fórmula', f"FY{context['year']-1}", context['ticker'], context['leader'], 'Promedio', 'n'],
            'rows': rows, 'diagnoses': context['diagnoses'], 'dupont': context['dupont'],
            'sources': sources, 'inputs': inputs,
            'notes': [f"Datos disponibles al {context['as_of']}. Ejercicios fiscales con fechas distintas; no son cotizaciones en tiempo real.",
                      'Promedio simple del grupo académico, no un índice oficial del sector. n excluye valores N/D.',
                      f"ROA: tasa académica {context['tax_rate']}%. Deuda: {'solo CP' if context['debt_basis']=='current' else 'CP + LP'}. EBITDA = utilidad operativa + D&A.",
                      'Capital de trabajo expresado en USD millones; las partidas base conservan su moneda original.',
                      'N/D significa información insuficiente o denominador no válido; nunca se sustituye por cero.',
                      *context['selected']['assumptions'],
                      f"Grupo aplicado: {dict(all='Todas las empresas del trabajo', chips='Diseño, chips y fundición', equipment='Equipos de semiconductores')[context['group']]}. Referente: {context['leader']}.",
                      'Conversión EUR/USD de cierre: 2022 = 1.0666; 2023 = 1.1050; 2024 = 1.0389; 2025 = 1.1750. Fuente: BCE (enlaces en fuentes).'],
            'warning': '', 'case': False, 'ticker': context['ticker'], 'source_year': context['year']}


def caso(reporte):
    ctx = reporte['contexto']
    rows = []
    for definition, r in zip(DEFINITIONS, reporte['filas']):
        key, _, _, unit, _, _ = definition
        rows.append({'label': r['nombre'], 'category': r['categoria'], 'formula': r['formula'],
                     'unit': 'S/' if unit == 'money' else unit, 'displays': [r['valor']],
                     'values': [reporte['resultado']['values'][key]], 'reason': r['motivo'], 'n': None})
    return {'title': 'Caso contable activo', 'subtitle': 'Ratios de tus libros contables',
            'period': f"{ctx['fecha_inicio'] or 'Sin fecha inicial'} al {ctx['fecha_cierre'] or 'sin fecha de cierre'}",
            'scope': 'Espacio anónimo actual - datos en soles, separados del comparativo externo.',
            'headers': ['Indicador / fórmula', 'Valor'], 'rows': rows,
            'diagnoses': [{'title': 'Ventas netas', 'status': fmt(ctx['total_ventas'], 'money') + ' S/', 'text': 'Ventas registradas en los libros.'},
                          {'title': 'Resultado neto', 'status': fmt(ctx['resultado_neto'], 'money') + ' S/', 'text': 'Sin impuestos ni ajustes inventados.'},
                          {'title': 'Registros', 'status': str(len(ctx['asientos'])) + ' asientos', 'text': 'Solo el caso de esta sesión.'}],
            'dupont': None, 'sources': [],
            'inputs': [[label, reporte['resultado']['inputs'].get(key), 'PEN', '', 'Libros del caso activo'] for key, label in FIELDS.items()],
            'notes': ['Los indicadores usan exclusivamente los registros del caso activo.',
                      'N/D: falta información, apertura documentada o un denominador válido. Cero y N/D tienen significados distintos.',
                      'Los indicadores de días usan el período documentado en los libros, no un año supuesto.',
                      'Intereses, depreciación y amortización solo se incluyen cuando están identificados.',
                      'La descarga no modifica asientos, partidas ni respaldos.'],
            'warning': ctx['nota_resultado'], 'case': True}


def enlace(url):
    try:
        return str(url) if urlsplit(str(url)).scheme in ('http', 'https') else ''
    except ValueError:
        return ''


def excel(datos):
    # Se integra con openpyxl, ya utilizado por Django para los siete reportes.
    # El servidor no necesita Node, un servicio externo ni nuevas dependencias.
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl.chart import BarChart, Reference
    from openpyxl.chart.marker import DataPoint
    from math import ceil
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.creator = 'BROADBROS'
    wb.properties.title = datos['subtitle']

    def cell(ws, row, col, value):
        c = ws.cell(row, col)
        c.value = float(value) if isinstance(value, Decimal) else value
        if isinstance(value, str):
            c.data_type = 's'  # Nunca ejecutar textos del visitante como fórmulas.
        c.font = Font(name='Calibri', size=11, color=TEAL)
        c.alignment = Alignment(vertical='top', wrap_text=True, indent=1 if row >= 6 and isinstance(value, str) else 0)
        return c

    def sheet(name, headers, widths):
        ws = wb.create_sheet(name)
        ws.sheet_view.showGridLines = False
        n = len(headers)
        for row, value in enumerate([datos['title'], datos['subtitle'], datos['period'], datos['scope']], 1):
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n)
            c = cell(ws, row, 1, value)
            c.font = Font(name='Calibri', size=21 if row == 1 else 11, bold=row <= 2, color=TEAL)
            ws.row_dimensions[row].height = max(32, 32*ceil(len(str(value))/max(25,sum(widths)*.45))) if row == 1 else 30
        for i, h in enumerate(headers, 1):
            c = cell(ws, 6, i, h)
            c.fill = PatternFill('solid', fgColor=TEAL)
            c.font = Font(name='Calibri', bold=True, color='FFFFFF', size=11)
        ws.row_dimensions[6].height = 32
        for i, width in enumerate(widths, 1): ws.column_dimensions[get_column_letter(i)].width = width
        ws.freeze_panes = 'B7'
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.print_title_rows = '1:6'
        ws.oddFooter.left.text = 'BROADBROS | Datos originales'
        ws.oddFooter.right.text = 'Página &P de &N'
        return ws

    summary = sheet('Resumen', ['Concepto', 'Resultado', 'Lectura'], [36, 28, 90])
    for i, d in enumerate(datos['diagnoses'], 7):
        for j, value in enumerate([d['title'], d['status'], d['text']], 1): cell(summary, i, j, value)
        summary.row_dimensions[i].height = 48
    for i, note in enumerate(([datos['warning']] if datos['warning'] else []) + datos['notes'], 12):
        summary.merge_cells(start_row=i, start_column=1, end_row=i, end_column=3)
        cell(summary, i, 1, note)
        summary.row_dimensions[i].height = max(32, 15 * (len(note) // 110 + 1))
    headers = (['Indicador', 'Categoría', 'Unidad', 'Valor', 'Fórmula', 'Dato pendiente'] if datos['case'] else
               ['Indicador', 'Categoría', 'Unidad', *datos['headers'][1:-1], 'Variación', 'n', 'Fórmula', 'Observación'])
    ws = sheet('17 indicadores', headers, [38, 18, 14, *([20, 60, 65] if datos['case'] else [19, 19, 19, 19, 19, 9, 62, 65])])
    for i, r in enumerate(datos['rows'], 7):
        values = [r['label'], r['category'], r['unit'], *[v if v is not None else 'N/D' for v in r['values']]]
        if not datos['case']: values += [r['numbers']['delta'] if r['numbers']['delta'] is not None else 'N/D', r['n']]
        values += [r['formula'], r.get('reason') or r.get('interpretation', '')]
        for j, value in enumerate(values, 1):
            c = cell(ws, i, j, value)
            if i % 2: c.fill = PatternFill('solid', fgColor=PALE)
            if 4 <= j < 4 + len(r['values']) and isinstance(value, (Decimal, int, float)):
                c.number_format = '0.00%' if r['unit'] == '%' else '#,##0.00;[Red](#,##0.00);0.00'
                c.alignment = Alignment(horizontal='right', vertical='top')
            if not datos['case'] and j == 8 and isinstance(value, Decimal):
                c.value = float(value * 100) if r['unit'] == '%' else float(value)
                c.number_format = '+0.00" pp";-0.00" pp";0.00" pp"' if r['unit'] == '%' else '+#,##0.00;-#,##0.00;0.00'
        ws.row_dimensions[i].height = max(58, 15*max(ceil(len(str(v))/max(10,ws.column_dimensions[get_column_letter(j)].width*.85)) for j,v in enumerate(values,1)))
    ws.auto_filter.ref = f'A6:{get_column_letter(len(headers))}{ws.max_row}'
    if not datos['case']:
        # Una sola unidad: no mezclar porcentajes, días e importes en un gráfico.
        metric = next(r for r in datos['rows'] if r['key'] == 'net_margin')
        chart_row = summary.max_row + 3
        cell(summary, chart_row, 1, 'Margen neto FY actual')
        for i, (label, value) in enumerate(zip(datos['headers'][2:5], metric['values'][1:]), chart_row+1):
            cell(summary, i, 1, label)
            c = cell(summary, i, 2, value if value is not None else 'N/D')
            c.number_format = '0.00%'
        chart = BarChart()
        chart.title = 'Margen neto - comparación'
        chart.y_axis.title = 'Porcentaje'
        chart.y_axis.numFmt = '0%'
        chart.add_data(Reference(summary, min_col=2, min_row=chart_row+1, max_row=chart_row+3), titles_from_data=False)
        chart.set_categories(Reference(summary, min_col=1, min_row=chart_row+1, max_row=chart_row+3))
        chart.legend = None
        chart.style = 13
        points = []
        for i, fill in enumerate((TEAL, '61A6B0', 'AD8856')):
            point = DataPoint(idx=i)
            point.graphicalProperties.solidFill = fill
            points.append(point)
        chart.series[0].data_points = points
        chart.width, chart.height = 20, 10
        summary.add_chart(chart, 'A'+str(chart_row+5))
    inputs = sheet('Partidas base', ['Partida', 'Valor', 'Unidad', 'Etiqueta de origen', 'Fuente'], [48, 22, 22, 58, 90])
    for i, values in enumerate(datos['inputs'], 7):
        for j, value in enumerate(values, 1):
            c = cell(inputs, i, j, 'N/D' if value is None else value)
            if j == 2 and value is not None: c.number_format = '#,##0.00;[Red](#,##0.00);0.00'
            if j == 5 and enlace(value): c.hyperlink = enlace(value)
        inputs.row_dimensions[i].height = max(40,15*max(ceil(len(str(v))/max(10,inputs.column_dimensions[get_column_letter(j)].width*.85)) for j,v in enumerate(values,1)))
    sources = sheet('Fuentes', ['Empresa', 'FY', 'Inicio', 'Cierre', 'Moneda', 'Enlace', 'Origen'], [22, 12, 18, 18, 15, 90, 18])
    entries = datos['sources'] or [['Caso activo', '', '', '', 'PEN', 'Libros de esta sesión', 'Contable']]
    for i, values in enumerate(entries, 7):
        for j, value in enumerate(values, 1):
            c = cell(sources, i, j, value)
            if j == 6 and enlace(value): c.hyperlink = enlace(value)
            if 2 <= j <= 5: c.alignment = Alignment(horizontal='center', vertical='top', wrap_text=True)
        sources.row_dimensions[i].height = max(36,15*max(ceil(len(str(v))/max(10,sources.column_dimensions[get_column_letter(j)].width*.85)) for j,v in enumerate(values,1)))
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def pdf(datos):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
    from reportlab.graphics.shapes import Drawing, Rect, String, Line
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from pathlib import Path
    fonts = Path(__file__).resolve().parent.parent / 'static' / 'fonts'
    if 'BroadBody' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('BroadBody', str(fonts / 'FiraMono-Regular.ttf')))
        pdfmetrics.registerFont(TTFont('BroadBold', str(fonts / 'FiraMono-Bold.ttf')))
        pdfmetrics.registerFontFamily('BroadBody', normal='BroadBody', bold='BroadBold', italic='BroadBody', boldItalic='BroadBold')
    output = BytesIO()
    width = 180 * mm
    color = lambda value: colors.HexColor('#' + value)
    normal = ParagraphStyle('normal', fontName='BroadBody', fontSize=9, leading=13, textColor=color(TEAL), spaceAfter=5)
    small = ParagraphStyle('small', parent=normal, fontSize=7.5, leading=10)
    title = ParagraphStyle('title', parent=normal, fontName='BroadBold', fontSize=23, leading=29, spaceAfter=12)
    heading = ParagraphStyle('heading', parent=normal, fontName='BroadBold', fontSize=13, leading=17, spaceBefore=12, spaceAfter=9)
    right = ParagraphStyle('right', parent=normal, alignment=TA_RIGHT, fontSize=9)
    white = ParagraphStyle('white', parent=small, textColor=colors.white, fontName='BroadBold')
    def p(text, style=normal): return Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
    def numero(value, column_width, detail=''):
        value = str(value)
        available = column_width - 18
        measured = pdfmetrics.stringWidth(value, 'BroadBody', 8.5)
        size = min(8.5, 8.5 * available / measured) if measured else 8.5
        style = ParagraphStyle('numero', parent=right, fontSize=size, leading=max(10, size*1.3), splitLongWords=False)
        text = escape(value) + ('<br/><font size="7">'+escape(detail)+'</font>' if detail else '')
        return Paragraph(text, style)
    def table(rows, widths, header=True):
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 9),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 9), ('TOPPADDING', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('LINEBELOW', (0, 0), (-1, -1), .3, color('D7E3E5'))]
        if header: commands += [('BACKGROUND', (0, 0), (-1, 0), color(TEAL))]
        for row in range(1 if header else 0, len(rows)):
            if row % 2: commands += [('BACKGROUND', (0, row), (-1, row), color('F2F7F7'))]
        t.setStyle(TableStyle(commands))
        return t
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(color('C8DADC'))
        canvas.line(15*mm, 15*mm, 195*mm, 15*mm)
        canvas.setFont('BroadBold', 9)
        canvas.setFillColor(color(TEAL))
        canvas.drawString(15*mm, 282*mm, 'B.  BROADBROS')
        canvas.setFont('BroadBody', 8)
        canvas.drawRightString(195*mm, 282*mm, 'ANÁLISIS FINANCIERO')
        canvas.setFont('BroadBody', 7)
        canvas.drawString(15*mm, 10*mm, 'Datos originales | Documento generado por BROADBROS')
        canvas.drawRightString(195*mm, 10*mm, f'Página {doc.page}')
        canvas.restoreState()
    story = [p(datos['title'], title), p(datos['subtitle'], heading), p(datos['period']), p(datos['scope'], small), Spacer(1, 14)]
    if datos['warning']: story += [p(datos['warning']), Spacer(1, 8)]
    for d in datos['diagnoses']:
        card = table([[p(d['title'], heading), p(d['status'], heading)], [p(d['text']), '']], [width*.38, width*.62], False)
        card.setStyle(TableStyle([('SPAN', (0,1), (-1,1))]))
        story.append(card)
        story.append(Spacer(1, 8))
    if not datos['case']:
        story += [p('Margen neto: empresa, referente y grupo', heading)]
        metric = next(r for r in datos['rows'] if r['key'] == 'net_margin')
        values = metric['values'][1:]
        available = [float(v) for v in values if v is not None]
        minimum, maximum = min([0, *available]), max([0, *available])
        span = maximum-minimum or 1
        chart = Drawing(width, 124)
        x0, barwidth = 96, 300
        zero = x0-minimum/span*barwidth
        chart.add(Line(zero, 10, zero, 110, strokeColor=color('C8DADC')))
        for i, (label, value, display) in enumerate(zip(datos['headers'][2:5], values, metric['displays'][1:])):
            y = 91-i*35
            chart.add(String(0, y+3, str(label), fontName='BroadBold', fontSize=10, fillColor=color(TEAL)))
            if value is not None and value:
                point = x0+(float(value)-minimum)/span*barwidth
                chart.add(Rect(min(zero,point), y-2, abs(point-zero), 15, fillColor=color([TEAL,'61A6B0','AD8856'][i]), strokeColor=None))
            chart.add(String(width, y+2, str(display), fontName='BroadBold', fontSize=10, textAnchor='end', fillColor=color(TEAL)))
        story += [chart, p('Las barras comparten escala y unidad. N/D no se dibuja como cero.', small)]
        dupont = datos['dupont']
        story += [p('ROE explicado con DuPont', heading), p(f"{dupont['margin']} margen neto × {dupont['turnover']} rotación × {dupont['multiplier']} multiplicador = {dupont['roe']} ROE."),
                  p('Los factores se calculan sin redondear previamente.', small)]
    else:
        story += [p('Cómo leer este informe', heading)] + [p(n) for n in datos['notes']]
    for categories, section in [(('Liquidez','Solvencia'), 'Liquidez y solvencia'), (('Gestión','Rentabilidad'), 'Gestión y rentabilidad')]:
        story += [PageBreak(), p(section, title), p(datos['subtitle']), p('Valores calculados con las mismas partidas y supuestos que la pantalla.', small), Spacer(1, 8)]
        headers = datos['headers'] if datos['case'] else datos['headers'][:-1] + ['Variación']
        widths = [width*.69, width*.31] if datos['case'] else [width*.375] + [width*.125]*5
        rows = [[p(h, white) for h in headers]]
        for r in datos['rows']:
            if r['category'] not in categories: continue
            note = '<br/>'+escape(r['reason']) if not datos['case'] and r.get('reason') else ''
            name = Paragraph('<b>'+escape(r['label'])+'</b><br/>'+escape(r['formula'])+'<br/><font color="#53696D">'+escape(r['unit'])+'</font>'+note, small)
            values = [numero(v, widths[j+1], 'n = '+str(r['n']) if not datos['case'] and j == 3 else '') for j, v in enumerate(r['displays'])]
            if datos['case'] and r['reason']:
                values[0] = Paragraph(escape(r['displays'][0])+'<br/>'+escape(r['reason']), small)
            rows.append([name, *values] + ([] if datos['case'] else [numero(r['delta'], widths[-1])]))
        story.append(table(rows, widths))
        story += [Spacer(1, 12), p('N/D: información insuficiente o denominador no válido. Los ceros registrados y las pérdidas válidas se conservan. Variaciones porcentuales en puntos porcentuales (pp), calculadas antes de redondear.', small)]
    if not datos['case']:
        story += [PageBreak(), p('Método y fuentes', title)]
        for note in datos['notes']: story.append(p(note, small))
        story += [Spacer(1, 8), p('Ejercicios y documentos de respaldo', heading)]
        rows = [[p(h, white) for h in ['Empresa / FY', 'Inicio', 'Cierre', 'Moneda', 'Fuente']]]
        for ticker, year, start, end, currency, url, origin in datos['sources']:
            if ticker == 'BCE' and int(year) not in (datos['source_year']-1, datos['source_year']): continue
            if year != str(datos['source_year']) and ticker not in (datos['ticker'], 'BCE'): continue
            link = enlace(url)
            source = Paragraph('<link href='+quoteattr(link)+' color="#2C666E">Consultar informe</link><br/>'+escape(origin), small) if link else p('Sin enlace / '+origin, small)
            rows.append([p(ticker+' / '+year, small), p(start, small), p(end, small), p(currency, small), source])
        sources_table = table(rows, [width*.22,width*.20,width*.20,width*.12,width*.26])
        sources_table.setStyle(TableStyle([('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        story.append(sources_table)
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=25*mm, bottomMargin=22*mm, title=datos['subtitle'], author='BROADBROS')
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
