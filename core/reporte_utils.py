"""Una misma fuente de saldos para pantalla, PDF y Excel."""
from decimal import Decimal
from collections import defaultdict
import re
from django.utils import timezone
from .models import CuentaContable, AsientoContable

CERO = Decimal('0')


def clase_asiento(asiento):
    return 'apertura' if asiento.descripcion=='Por los saldos de apertura del ejercicio' else asiento.clase


def es_efectivo(cuenta):
    return cuenta.tipo=='activo' and (cuenta.codigo.startswith('10') or bool(re.search(r'\bcaja\b|\bbancos?\b|cuentas? corrientes?',cuenta.nombre,re.I)))


def flujo_asiento(asiento, movimientos, neto):
    if asiento.flujo_efectivo!='pendiente':return asiento.flujo_efectivo
    contrapartidas=[m for m in movimientos if not es_efectivo(m.cuenta)]
    if not contrapartidas:return 'operacion'  # Transferencia entre caja y banco: neto cero.
    if all(m.cuenta.tipo=='patrimonio' or m.cuenta.codigo.startswith('45') for m in contrapartidas):return 'financiacion'
    if neto<0 and all(m.cuenta.codigo.startswith('33') for m in contrapartidas if m.tipo=='debe') and any(m.tipo=='debe' for m in contrapartidas):return 'inversion'
    if all(m.cuenta.tipo in ('ingreso','gasto') or m.cuenta.codigo.startswith('12') for m in contrapartidas):return 'operacion'
    return 'pendiente'


def get_reporte_context():
    asientos = list(AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('fecha', 'id'))
    cuentas = list(CuentaContable.objects.all())
    totales=defaultdict(lambda:{'debe':CERO,'haber':CERO})
    operativos=defaultdict(lambda:{'debe':CERO,'haber':CERO})
    aperturas=defaultdict(lambda:CERO)
    cierres=defaultdict(lambda:CERO)
    movimientos_cuenta=defaultdict(list)
    flujos={k:CERO for k in ('operacion','inversion','financiacion','pendiente')}
    efectivo_inicial=CERO;efectivo_final=CERO;pendientes_flujo=[]
    for numero,asiento in enumerate(asientos,1):
        asiento.numero=numero
        movimientos=list(asiento.movimientos.all())
        clase=clase_asiento(asiento)
        neto=CERO
        for mov in movimientos:
            mov.asiento=asiento
            firmado=mov.monto*(1 if mov.tipo=='debe' else -1)
            movimientos_cuenta[mov.cuenta_id].append(mov)
            totales[mov.cuenta_id][mov.tipo]+=mov.monto
            if clase=='operacion':operativos[mov.cuenta_id][mov.tipo]+=mov.monto
            if clase=='apertura':aperturas[mov.cuenta_id]-=firmado
            if clase=='cierre':cierres[mov.cuenta_id]-=firmado
            if es_efectivo(mov.cuenta):neto+=firmado
        efectivo_final+=neto
        if clase=='apertura':efectivo_inicial+=neto
        elif neto:
            categoria=flujo_asiento(asiento,movimientos,neto)
            flujos[categoria]+=neto
            if categoria=='pendiente':pendientes_flujo.append(f'Asiento {numero}: {asiento.descripcion}')
    balance, mayor = [], []
    activo_corriente, activo_no_corriente = [], []
    pasivo_corriente, pasivo_no_corriente, patrimonio = [], [], []
    er = {k: [] for k in ('ventas', 'costo_ventas', 'gastos_operativos', 'gastos_financieros', 'otros_ingresos', 'otros_gastos','impuesto_ganancias')}
    ecp=[];transferido=CERO
    for cuenta in cuentas:
        t = totales.get(cuenta.pk, {'debe': CERO, 'haber': CERO})
        d, h = t['debe'], t['haber']
        if not d and not h:
            continue
        diferencia = d - h
        balance.append({'cuenta': cuenta, 'total_debe': d, 'total_haber': h,
                        'saldo_deudor': max(diferencia, CERO), 'saldo_acreedor': max(-diferencia, CERO)})
        saldo = diferencia if cuenta.tipo in ('activo', 'gasto') else -diferencia
        movs = movimientos_cuenta[cuenta.pk]
        mayor.append({'cuenta': cuenta, 'movimientos': movs, 'total_debe': d, 'total_haber': h, 'saldo_final': saldo,'saldo':saldo})
        item = {'cuenta': cuenta, 'saldo': saldo}
        # Las cuentas correctoras del activo (39) conservan su saldo negativo.
        try:
            grupo = int(cuenta.codigo[:2])
        except ValueError:
            grupo = 0
        if cuenta.tipo == 'activo':
            from .clasificacion import activo_no_corriente as clasificar_activo
            (activo_no_corriente if clasificar_activo(cuenta.codigo, cuenta.nombre, cuenta.subcategoria) else activo_corriente).append(item)
        elif cuenta.tipo == 'pasivo':
            if cuenta.codigo.startswith('4011') and saldo < 0:
                activo_corriente.append({'cuenta': cuenta, 'saldo': -saldo})
            else:
                no_corriente = (cuenta.subcategoria == 'pasivo_no_corriente' or
                                (cuenta.subcategoria != 'pasivo_corriente' and 47 <= grupo <= 49))
                (pasivo_no_corriente if no_corriente else pasivo_corriente).append(item)
        elif cuenta.tipo == 'patrimonio':
            patrimonio.append(item)
            inicial=aperturas[cuenta.pk];resultado=cierres[cuenta.pk]
            transferido+=resultado
            ecp.append({'nombre':f'{cuenta.codigo} · {cuenta.nombre}','inicial':inicial,'variacion':saldo-inicial-resultado,'resultado':resultado,'final':saldo})
        else:
            # El destino analítico 9/79 no vuelve a reconocer el gasto por naturaleza.
            if cuenta.codigo.startswith('9') or grupo==79:
                continue
            op=operativos[cuenta.pk]
            item={'cuenta':cuenta,'saldo':op['haber']-op['debe'] if cuenta.tipo=='ingreso' else op['debe']-op['haber']}
            if cuenta.tipo == 'ingreso':
                clave = 'otros_ingresos' if cuenta.subcategoria == 'otro_ingreso' or grupo in (73,75,76,77) else 'ventas'
            else:
                clave = {'costo_ventas': 'costo_ventas', 'gasto_financiero': 'gastos_financieros', 'otro_gasto': 'otros_gastos','impuesto_ganancias':'impuesto_ganancias'}.get(cuenta.subcategoria)
                if clave is None:
                    clave = 'impuesto_ganancias' if grupo in (87,88) else 'costo_ventas' if grupo == 69 else 'gastos_financieros' if grupo==67 else 'otros_gastos' if grupo == 66 else 'gastos_operativos'
            er[clave].append(item)

    suma = lambda items: sum((item['saldo'] for item in items), CERO)
    ctx = {'asientos': asientos, 'bal_comp_datos': balance, 'mayor_datos': mayor,
           'fecha_inicio': asientos[0].fecha if asientos else None,
           'fecha_cierre': max([a.fecha_cierre_ejercicio for a in asientos if a.fecha_cierre_ejercicio] + [asientos[-1].fecha]) if asientos else None, 'generado_el': timezone.localtime(),
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
    ctx['resultado_neto']=ctx['utilidad_antes_impuesto']-ctx['total_impuesto_ganancias']
    ctx['resultados_acumulados'] = ctx['resultado_neto']-transferido
    ecp.append({'nombre':'Resultado del período por incorporar','inicial':CERO,'variacion':CERO,'resultado':ctx['resultados_acumulados'],'final':ctx['resultados_acumulados']})
    ctx['filas_patrimonio']=ecp
    ctx['totales_patrimonio']={k:sum((r[k] for r in ecp),CERO) for k in ('inicial','variacion','resultado','final')}
    ctx['nota_patrimonio']='Los saldos iniciales proceden de los asientos de apertura identificados. Si no se proporcionó apertura, se muestran los movimientos registrados, sin presumir saldos anteriores.'
    ctx['filas_flujos']=[('Actividades de operación',flujos['operacion'],'detalle'),('Actividades de inversión',flujos['inversion'],'detalle'),('Actividades de financiación',flujos['financiacion'],'detalle')]
    if pendientes_flujo:ctx['filas_flujos'].append(('Flujos pendientes de clasificación',flujos['pendiente'],'detalle'))
    ctx['filas_flujos'] += [('Variación neta de efectivo',efectivo_final-efectivo_inicial,'subtotal'),('Efectivo inicial documentado',efectivo_inicial,'detalle'),('EFECTIVO FINAL REGISTRADO',efectivo_final,'total')]
    ctx['pendientes_flujo']=pendientes_flujo
    ctx['nota_flujos']='Flujos calculados a partir de cobros y pagos registrados; las operaciones sin efectivo se excluyen. Revise la clasificación de los asientos señalados y los saldos de apertura.'
    ctx['nota_resultado'] = (
        'Resultado provisional: el caso no proporciona costo de ventas ni inventario final. '
        'Los saldos muestran únicamente los movimientos registrados, sin un ajuste de existencias.'
        if ctx['total_ventas'] and not ctx['total_costo_ventas'] and any(c.codigo.startswith('20') for c in cuentas if c.pk in totales) and
        any(a.descripcion == 'Por los saldos de apertura del ejercicio' for a in asientos)
        else ''
    )
    pendientes_importacion = [a.observaciones_importacion for a in asientos if a.observaciones_importacion]
    if pendientes_importacion:
        ctx['nota_resultado'] = 'Registro parcial del ejercicio. Datos pendientes: ' + ' / '.join(dict.fromkeys(pendientes_importacion))
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
    filas = [('Ventas netas', ctx['total_ventas'], 'detalle'),
            ('Costo de ventas', -ctx['total_costo_ventas'], 'detalle'),
            ('Utilidad bruta', ctx['utilidad_bruta'], 'subtotal'),
            ('Gastos operativos', -ctx['total_gastos_operativos'], 'detalle'),
            ('Utilidad operativa', ctx['utilidad_operativa'], 'subtotal'),
            ('Gastos financieros', -ctx['total_gastos_financieros'], 'detalle'),
            ('Otros ingresos', ctx['total_otros_ingresos'], 'detalle'),
            ('Otros gastos', -ctx['total_otros_gastos'], 'detalle'),
            ('RESULTADO ANTES DE IMPUESTOS', ctx['utilidad_antes_impuesto'], 'total')]
    if ctx['total_impuesto_ganancias']:
        filas[-1] = ('Resultado antes de impuestos', ctx['utilidad_antes_impuesto'], 'subtotal')
        filas.extend([('Impuesto a las ganancias registrado', -ctx['total_impuesto_ganancias'], 'detalle'),
                      ('RESULTADO NETO DEL PERÍODO', ctx['resultado_neto'], 'total')])
    return filas


def contexto_estados():
    ctx = get_reporte_context()
    from itertools import zip_longest
    ctx['filas_activo'] = filas_situacion(ctx, 'activo')
    ctx['filas_pasivo'] = filas_situacion(ctx, 'pasivo')
    ctx['filas_esf'] = list(zip_longest(ctx['filas_activo'], ctx['filas_pasivo']))
    ctx['filas_er'] = filas_resultados(ctx)
    return ctx
