"""Explicaciones breves de los ratios calculados, sin delegar cifras a una IA."""
import re
from .validacion_contable import texto


ALIASES = {
    'ebitda_margin': ('margen ebitda',),
    'debt_cover': ('deuda financiera', 'deuda/ebitda', 'deuda / ebitda', 'cobertura de endeudamiento'),
    'debt_ratio': ('porcentaje de endeudamiento', 'ratio de endeudamiento', 'pasivo sobre activo'),
    'interest_cover': ('cobertura de intereses',),
    'working_capital': ('capital de trabajo',),
    'cash_cycle': ('ciclo de efectivo', 'ciclo de caja'),
    'quick': ('prueba acida', 'liquidez acida'),
    'gross_margin': ('margen bruto',), 'operating_margin': ('margen operativo',),
    'net_margin': ('margen neto',),
    'receivable_days': ('dias de cuentas por cobrar', 'dias de cobro', 'dias cxc'),
    'payable_days': ('dias de cuentas por pagar', 'dias de pago', 'dias cxp'),
    'inventory_days': ('dias de inventario',),
    'leverage': ('endeudamiento contable', 'apalancamiento'),
    'roe': ('roe', 'patrimonio del accionista'), 'roa': ('roa',),
    'current': ('liquidez corriente', 'razon corriente', 'ratio corriente', 'liquidez'),
}


def indicador_consultado(mensaje):
    n=texto(mensaje)
    return next((key for key,terms in ALIASES.items()
                 if any(re.search(r'\b'+re.escape(term)+r'\b',n) for term in terms)), '')


def quiere_detalle(mensaje):
    return bool(re.search(r'paso a paso|sustituc|formula|como (?:se )?calcul|desglos|detalle',texto(mensaje)))


def respuesta_ratios_caso(mensaje):
    n=texto(mensaje)
    # Las empresas externas se consultan desde su propio ámbito, nunca con los libros.
    if re.search(r'\b(avgo|broadcom|nvda|nvidia|amd|asml|intel|csco|amat|lrcx|kla)\b',n):return None
    key=indicador_consultado(mensaje)
    resumen=bool(re.search(r'ratios?|indicadores? financier|(?:mi|el|este) caso.*(?:solvente|rentable)|(?:mi|esta) empresa.*(?:solvente|rentable)',n))
    if not key and not resumen:return None
    from .ratios_caso import calcular_caso
    from .ratios import DEFINITIONS
    from .ratio_lab import MEANING
    report=calcular_caso()
    filas={definition[0]:fila for definition,fila in zip(DEFINITIONS,report['filas'])}
    if not key:
        return ('Caso contable activo\n'+
                '\n'.join(f"• {filas[k]['nombre']}: {filas[k]['valor']}." for k in ('current','debt_ratio','net_margin'))+
                '\nLa liquidez orienta sobre pagos; el endeudamiento, sobre financiación; el margen, sobre rentabilidad. '
                'N/D significa que falta información o el cálculo no es válido. ¿Cuál explicamos?')
    fila=filas[key];value=report['resultado']['values'][key]
    meaning=MEANING[key]
    if key=='receivable_days':meaning='Días medios de cobro con ventas al crédito y el período documentado del caso.'
    if key=='payable_days':meaning='Días medios de pago con compras al crédito y el período documentado del caso.'
    if key=='net_margin':meaning='Utilidad neta del caso por cada unidad de ventas.'
    if key=='roe':meaning='Utilidad neta del caso respecto a su patrimonio promedio; más deuda también puede elevarlo.'
    answer=f"Caso contable activo · {fila['nombre']}: {fila['valor']}.\n{meaning}"
    if value is None:
        answer+='\nPara calcularlo: '+(fila['motivo'] or 'completa las partidas y el período requeridos.')+' N/D no significa cero.'
    elif key=='current':
        answer+=f'\nEn sencillo: por cada S/ 1 de obligación corriente tienes S/ {value:,.2f} de activo corriente. No todo ese activo es efectivo.'
    elif key in ('gross_margin','operating_margin','net_margin'):
        answer+=f'\nPor cada S/ 100 de ventas, el resultado de este margen es S/ {value*100:,.2f}.'
    elif key=='debt_ratio':
        answer+=f'\nDe cada S/ 100 de activos, S/ {value*100:,.2f} están financiados por pasivos.'
    if quiere_detalle(mensaje):answer+='\nFórmula: '+fila['formula']+'. Se usan las mismas partidas del reporte, sin suponer datos.'
    return answer
