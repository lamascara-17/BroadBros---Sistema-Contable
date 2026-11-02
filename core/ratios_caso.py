"""Ratios del caso activo: sin ventas/créditos ni saldos iniciales supuestos."""
from decimal import Decimal
from .ratios import calculate, DEFINITIONS, fmt
from .reporte_utils import contexto_estados, es_efectivo, clase_asiento


def calcular_caso():
    ctx = contexto_estados()
    valores = {'current_assets': ctx['total_activo_corriente'], 'current_liabilities': ctx['total_pasivo_corriente'],
               'assets': ctx['total_activos'], 'liabilities': ctx['total_pasivos'],
               'equity': ctx['total_patrimonio_con_resultados'], 'total_equity': ctx['total_patrimonio_con_resultados']}
    mayor = ctx['mayor_datos']
    suma = lambda criterio: sum((r['saldo_final'] for r in mayor if criterio(r['cuenta'])), Decimal('0'))
    valores['cash'] = suma(es_efectivo)
    valores['receivables'] = suma(lambda c: c.tipo == 'activo' and c.codigo.startswith('12'))
    valores['inventory'] = suma(lambda c: c.tipo == 'activo' and c.codigo.startswith('20'))
    valores['payables'] = suma(lambda c: c.tipo == 'pasivo' and c.codigo.startswith('42'))
    valores['debt_current'] = suma(lambda c: c.tipo == 'pasivo' and c.codigo.startswith('45') and c.subcategoria == 'pasivo_corriente') if all(r['cuenta'].subcategoria in ('pasivo_corriente', 'pasivo_no_corriente') for r in mayor if r['cuenta'].codigo.startswith('45')) else None
    valores['debt_noncurrent'] = suma(lambda c: c.tipo == 'pasivo' and c.codigo.startswith('45') and c.subcategoria == 'pasivo_no_corriente') if valores['debt_current'] is not None else None
    if not ctx['asientos']:
        valores = {}
    elif not ctx['nota_resultado']:
        valores.update(revenue=ctx['total_ventas'], cost_sales=ctx['total_costo_ventas'],
                       operating_income=ctx['utilidad_operativa'], net_income=ctx['resultado_neto'])
    aperturas = [a for a in ctx['asientos'] if clase_asiento(a) == 'apertura']
    movs = [m for a in aperturas for m in a.movimientos.all()]
    if movs:
        def inicial(criterio, deudor=True):
            seleccion = [m for m in movs if criterio(m.cuenta)]
            if not seleccion: return None
            return sum((m.monto * (1 if (m.tipo == 'debe') == deudor else -1) for m in seleccion), Decimal('0'))
        valores['assets_previous'] = inicial(lambda c: c.tipo == 'activo')
        valores['equity_previous'] = inicial(lambda c: c.tipo == 'patrimonio', False)
        for clave, prefijo, tipo, deudor in [('receivables', '12', 'activo', True), ('inventory', '20', 'activo', True), ('payables', '42', 'pasivo', False)]:
            valores[clave+'_previous'] = inicial(lambda c: c.tipo == tipo and c.codigo.startswith(prefijo), deudor)
    periodo = (ctx['fecha_cierre'] - min(a.fecha for a in aperturas)).days + 1 if aperturas and ctx['fecha_cierre'] else None
    if ctx['asientos'] and not ctx['nota_resultado']:
        ventas_credito, compras_credito = Decimal('0'), Decimal('0')
        hay_ventas, hay_compras = False, False
        for a in ctx['asientos']:
            if clase_asiento(a) != 'operacion': continue
            movimientos = list(a.movimientos.all())
            if any(m.cuenta.tipo == 'ingreso' and m.cuenta.codigo.startswith('70') for m in movimientos):
                hay_ventas = True
                ventas_credito += sum((m.monto * (1 if m.tipo == 'debe' else -1) for m in movimientos if m.cuenta.tipo == 'activo' and m.cuenta.codigo.startswith('12')), Decimal('0'))
            if any(m.cuenta.codigo.startswith('20') and m.tipo == 'debe' for m in movimientos):
                hay_compras = True
                compras_credito += sum((m.monto for m in movimientos if m.cuenta.codigo.startswith('42') and m.tipo == 'haber'), Decimal('0'))
        if hay_ventas: valores['credit_revenue'] = ventas_credito
        if hay_compras: valores['credit_purchases'] = compras_credito
        import re
        # Los cierres cancelan saldos de gasto, pero no el gasto del periodo.
        gastos = [m for a in ctx['asientos'] if clase_asiento(a) == 'operacion'
                  for m in a.movimientos.all() if m.cuenta.tipo == 'gasto' and not m.cuenta.codigo.startswith(('9', '79'))]
        def gasto_periodo(patron):
            seleccion = [m for m in gastos if re.search(patron, m.cuenta.nombre, re.I)]
            return sum((m.monto * (1 if m.tipo == 'debe' else -1) for m in seleccion), Decimal('0')) if seleccion else None
        valores['interest'] = gasto_periodo(r'inter[eé]s')
        valores['da'] = gasto_periodo(r'depreciaci[oó]n|amortizaci[oó]n')
    # Los datos no documentados permanecen ausentes.
    resultado = calculate(valores, tax_rate=None, period_days=periodo, allow_approximations=False)
    filas = []
    for key, nombre, categoria, unidad, formula, _ in DEFINITIONS:
        filas.append({'nombre': nombre, 'categoria': categoria, 'formula': formula.replace('365', str(periodo)) if periodo is not None else formula,
                      'valor': fmt(resultado['values'][key], 'S/' if unidad == 'money' else unidad),
                      'motivo': resultado['reasons'].get(key, '')})
    return {'rotacion_inventario': fmt(resultado['values']['_inventory_turnover']), 'filas': filas, 'contexto': ctx, 'resultado': resultado}
