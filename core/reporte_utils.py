"""Una misma fuente de saldos para pantalla, PDF y Excel."""
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from .models import CuentaContable, AsientoContable, Movimiento

CERO = Decimal('0')


def get_reporte_context():
    asientos = list(AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('fecha', 'id'))
    cuentas = list(CuentaContable.objects.all())
    totales = {}
    for fila in Movimiento.objects.values('cuenta_id', 'tipo').annotate(total=Sum('monto')):
        totales.setdefault(fila['cuenta_id'], {'debe': CERO, 'haber': CERO})[fila['tipo']] = fila['total']
    balance, mayor = [], []
    activo_corriente, activo_no_corriente = [], []
    pasivo_corriente, pasivo_no_corriente, patrimonio = [], [], []
    er = {k: [] for k in ('ventas', 'costo_ventas', 'gastos_operativos', 'gastos_financieros', 'otros_ingresos', 'otros_gastos')}
    for cuenta in cuentas:
        t = totales.get(cuenta.pk, {'debe': CERO, 'haber': CERO})
        d, h = t['debe'], t['haber']
        if not d and not h:
            continue
        diferencia = d - h
        balance.append({'cuenta': cuenta, 'total_debe': d, 'total_haber': h,
                        'saldo_deudor': max(diferencia, CERO), 'saldo_acreedor': max(-diferencia, CERO)})
        saldo = diferencia if cuenta.tipo in ('activo', 'gasto') else -diferencia
        movs = [mov for asiento in asientos for mov in asiento.movimientos.all() if mov.cuenta_id == cuenta.pk]
        mayor.append({'cuenta': cuenta, 'movimientos': movs, 'total_debe': d, 'total_haber': h, 'saldo_final': saldo})
        item = {'cuenta': cuenta, 'saldo': saldo}
        # Las cuentas correctoras del activo (39) conservan su saldo negativo.
        try:
            grupo = int(cuenta.codigo[:2])
        except ValueError:
            grupo = 0
        if cuenta.tipo == 'activo':
            (activo_no_corriente if 30 <= grupo <= 39 else activo_corriente).append(item)
        elif cuenta.tipo == 'pasivo':
            (pasivo_no_corriente if 47 <= grupo <= 49 else pasivo_corriente).append(item)
        elif cuenta.tipo == 'patrimonio':
            patrimonio.append(item)
        else:
            if cuenta.tipo == 'ingreso':
                clave = 'otros_ingresos' if cuenta.subcategoria == 'otro_ingreso' or grupo == 75 else 'ventas'
            else:
                clave = {'costo_ventas': 'costo_ventas', 'gasto_financiero': 'gastos_financieros', 'otro_gasto': 'otros_gastos'}.get(cuenta.subcategoria)
                if clave is None:
                    clave = 'costo_ventas' if grupo == 69 else 'otros_gastos' if grupo == 66 else 'gastos_operativos'
            er[clave].append(item)

    suma = lambda items: sum((item['saldo'] for item in items), CERO)
    ctx = {'asientos': asientos, 'bal_comp_datos': balance, 'mayor_datos': mayor,
           'fecha_inicio': asientos[0].fecha if asientos else None,
           'fecha_cierre': asientos[-1].fecha if asientos else None, 'generado_el': timezone.localtime(),
           'activo_corriente': activo_corriente, 'activo_no_corriente': activo_no_corriente,
           'pasivo_corriente': pasivo_corriente, 'pasivo_no_corriente': pasivo_no_corriente,
           'patrimonio': patrimonio, **er}
    for clave in ('total_debe', 'total_haber', 'saldo_deudor', 'saldo_acreedor'):
        ctx['gran_' + clave] = sum((item[clave] for item in balance), CERO)
    for clave in er:
        ctx['total_' + clave] = suma(er[clave])
    ctx['utilidad_bruta'] = ctx['total_ventas'] - ctx['total_costo_ventas']
    ctx['utilidad_operativa'] = ctx['utilidad_bruta'] - ctx['total_gastos_operativos']
    ctx['utilidad_antes_impuesto'] = ctx['utilidad_operativa'] - ctx['total_gastos_financieros'] + ctx['total_otros_ingresos'] - ctx['total_otros_gastos']
    # No se presume una tasa tributaria ni un gasto que no esté registrado.
    ctx['resultados_acumulados'] = ctx['utilidad_antes_impuesto']
    for clave in ('activo_corriente', 'activo_no_corriente', 'pasivo_corriente', 'pasivo_no_corriente', 'patrimonio'):
        ctx['total_' + clave] = suma(ctx[clave])
    ctx['activos'] = activo_corriente + activo_no_corriente
    ctx['pasivos'] = pasivo_corriente + pasivo_no_corriente
    ctx['total_activos'] = suma(ctx['activos'])
    ctx['total_pasivos'] = suma(ctx['pasivos'])
    ctx['total_patrimonio_con_resultados'] = ctx['total_patrimonio'] + ctx['resultados_acumulados']
    ctx['total_pasivo_patrimonio'] = ctx['total_pasivos'] + ctx['total_patrimonio_con_resultados']
    ctx['esta_balanceado'] = ctx['total_activos'] == ctx['total_pasivo_patrimonio']
    return ctx


def filas_situacion(ctx, lado):
    """Filas del ESF utilizadas también por el libro Excel."""
    filas = []
    grupos = [('Activo corriente', 'activo_corriente'), ('Activo no corriente', 'activo_no_corriente')] if lado == 'activo' else [('Pasivo corriente', 'pasivo_corriente'), ('Pasivo no corriente', 'pasivo_no_corriente')]
    for titulo, clave in grupos:
        filas.append((titulo, None, 'seccion'))
        filas.extend((f"{i['cuenta'].codigo} · {i['cuenta'].nombre}", i['saldo'], 'detalle') for i in ctx[clave])
        filas.append((f'Total {titulo.lower()}', ctx['total_' + clave], 'subtotal'))
    if lado == 'activo':
        filas.append(('TOTAL ACTIVO', ctx['total_activos'], 'total'))
    else:
        filas += [('TOTAL PASIVO', ctx['total_pasivos'], 'subtotal'), ('Patrimonio', None, 'seccion')]
        filas.extend((f"{i['cuenta'].codigo} · {i['cuenta'].nombre}", i['saldo'], 'detalle') for i in ctx['patrimonio'])
        filas += [('Resultado del ejercicio', ctx['resultados_acumulados'], 'detalle'),
                  ('Total patrimonio', ctx['total_patrimonio_con_resultados'], 'subtotal'),
                  ('TOTAL PASIVO Y PATRIMONIO', ctx['total_pasivo_patrimonio'], 'total')]
    return filas


def filas_resultados(ctx):
    return [('Ventas netas', ctx['total_ventas'], 'detalle'),
            ('Costo de ventas', -ctx['total_costo_ventas'], 'detalle'),
            ('Utilidad bruta', ctx['utilidad_bruta'], 'subtotal'),
            ('Gastos operativos', -ctx['total_gastos_operativos'], 'detalle'),
            ('Utilidad operativa', ctx['utilidad_operativa'], 'subtotal'),
            ('Gastos financieros', -ctx['total_gastos_financieros'], 'detalle'),
            ('Otros ingresos', ctx['total_otros_ingresos'], 'detalle'),
            ('Otros gastos', -ctx['total_otros_gastos'], 'detalle'),
            ('RESULTADO ANTES DE IMPUESTOS', ctx['utilidad_antes_impuesto'], 'total')]


def contexto_estados():
    ctx = get_reporte_context()
    from itertools import zip_longest
    ctx['filas_activo'] = filas_situacion(ctx, 'activo')
    ctx['filas_pasivo'] = filas_situacion(ctx, 'pasivo')
    ctx['filas_esf'] = list(zip_longest(ctx['filas_activo'], ctx['filas_pasivo']))
    ctx['filas_er'] = filas_resultados(ctx)
    return ctx
