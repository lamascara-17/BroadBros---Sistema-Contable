"""Respuestas sobre saldos reales sin pedir a un modelo que los recalcule."""
import re
from .validacion_contable import texto
from .reporte_utils import contexto_estados


def respuesta_calculada(mensaje):
    n = texto(mensaje)
    utilidad = bool(re.search(r'(?:cual|cuanto|dime|muestra).*\b(?:utilidad|resultado neto)\b', n))
    balance = bool(re.search(r'\bbalance\b.*(?:cuadra|cuadrado)|(?:cuadra|cuadrado).*\bbalance\b', n))
    errores = bool(re.search(r'que (?:operaciones|asientos).*(?:mal|incorrect)|inconsistencias.*(?:caso|registros)', n))
    if not any((utilidad,balance,errores)): return None
    ctx = contexto_estados()
    if not ctx['asientos']: return 'No hay asientos registrados en tu espacio de trabajo. Registra o importa un caso para consultar sus resultados.'
    if utilidad:
        return f"El resultado registrado del período es S/ {ctx['resultado_neto']:,.2f}. " + (ctx['nota_resultado'] or 'Corresponde a los ingresos y gastos registrados; no se han supuesto impuestos ni ajustes adicionales.')
    if balance:
        return ('La ecuación contable está cuadrada. ' if ctx['esta_balanceado'] else 'La ecuación contable presenta una diferencia. ') + f"Activo S/ {ctx['total_activos']:,.2f}; pasivo S/ {ctx['total_pasivos']:,.2f}; patrimonio S/ {ctx['total_patrimonio_con_resultados']:,.2f}. " + (' '.join(ctx['notas_consistencia']) or 'El cuadre matemático no demuestra que todas las operaciones estén correctamente interpretadas.')
    return ' '.join(ctx['notas_consistencia'] + ctx['notas_plan']) or 'Los controles actuales no detectan diferencias matemáticas o de clasificación. Compara los registros con el enunciado: esto no garantiza que no existan otras omisiones.'
