"""Reglas del ciclo contable simplificado; la visión transcribe, Python calcula."""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENTIMO = Decimal('0.01')
CUENTAS = {
    '10': ('Efectivo y equivalentes de efectivo', 'activo', ''),
    '12': ('Cuentas por cobrar comerciales', 'activo', ''),
    '20': ('Mercaderías', 'activo', ''),
    '33': ('Propiedad, planta y equipo', 'activo', ''),
    '39': ('Depreciación acumulada', 'activo', ''),
    '41': ('Remuneraciones por pagar', 'pasivo', ''),
    '42': ('Cuentas por pagar comerciales', 'pasivo', ''),
    '50': ('Capital social', 'patrimonio', ''),
    '62': ('Gastos de personal', 'gasto', 'gasto_operativo'),
    '63': ('Servicios prestados por terceros', 'gasto', 'gasto_operativo'),
    '66': ('Pérdida de activos', 'gasto', 'otro_gasto'),
    '68': ('Gastos de depreciación', 'gasto', 'gasto_operativo'),
    '69': ('Costo de ventas', 'gasto', 'costo_ventas'),
    '70': ('Ventas', 'ingreso', ''),
    '75': ('Otros ingresos de gestión', 'ingreso', 'otro_ingreso'),
}


def decimal(valor, campo, minimo=Decimal('0')):
    try:
        if isinstance(valor, bool) or valor is None:
            raise ValueError
        n = Decimal(str(valor))
        if not n.is_finite() or n < minimo or n >= Decimal('10000000000'):
            raise ValueError
        return n
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError(f'El campo {campo} debe contener un número válido.') from None


def moneda(valor, campo='monto', permite_cero=False):
    n = decimal(valor, campo)
    if n != n.quantize(CENTIMO) or (n == 0 and not permite_cero):
        raise ValueError(f'El campo {campo} debe ser positivo y tener como máximo dos decimales.')
    return n


def fecha(valor):
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ValueError(f'Fecha ilegible o inválida: {valor}.') from None


def generar_asientos(datos):
    """Genera operaciones y ajustes sin deducir importes mediante un modelo."""
    if not isinstance(datos, dict) or datos.get('observaciones'):
        raise ValueError('La lectura contiene datos pendientes de aclarar. Use una imagen más nítida.')
    operaciones = datos.get('operaciones')
    if not isinstance(operaciones, list) or not operaciones:
        raise ValueError('No se identificaron operaciones en la imagen.')
    if datos.get('metodo_inventario') != 'periodico':
        raise ValueError('Esta importación requiere un caso de inventario periódico. No se guardó ningún asiento.')
    cierre = fecha(datos.get('fecha_cierre'))
    inicial = datos.get('inventario_inicial')
    if inicial is None and datos.get('empresa_nueva') is True:
        inicial = '0'
    inventario = moneda(inicial, 'inventario inicial', permite_cero=True)
    if inventario:
        raise ValueError('El caso contiene inventario inicial. Se requieren saldos de apertura completos; use el registro manual para este caso.')
    asientos, activos, facturas = [], [], []
    cierre_inventario = None

    def movimiento(codigo, tipo, monto):
        nombre, tipo_cuenta, subcategoria = CUENTAS[codigo]
        return {'codigo': codigo, 'nombre': nombre, 'tipo_cuenta': tipo_cuenta,
                'subcategoria': subcategoria, 'tipo_movimiento': tipo, 'monto': monto}

    def asiento(dia, glosa, lineas):
        lineas = [(c, t, m) for c, t, m in lineas if m != 0]
        if len(lineas) < 2:
            raise ValueError('Una operación no contiene dos movimientos válidos.')
        debe = sum(m for _, t, m in lineas if t == 'debe')
        haber = sum(m for _, t, m in lineas if t == 'haber')
        if debe != haber:
            raise ValueError('La operación no cumple la partida doble.')
        asientos.append({'fecha': dia, 'descripcion': glosa,
                         'movimientos': [movimiento(c, t, m) for c, t, m in lineas]})

    # Convención del ciclo simplificado: compra sin condición de crédito, al contado.
    # Mantener el orden original cuando hay varias operaciones el mismo día.
    orden = sorted(operaciones, key=lambda op: fecha(op.get('fecha')) if isinstance(op, dict) else date.min)
    for op in orden:
        if not isinstance(op, dict) or not str(op.get('texto', '')).strip():
            raise ValueError('Cada operación debe incluir el texto leído de la imagen.')
        dia = fecha(op.get('fecha'))
        if dia > cierre:
            raise ValueError('Existe una operación posterior al cierre indicado.')
        tipo = op.get('tipo')
        if op.get('igv') not in (None, 0, '0'):
            raise ValueError('El caso incluye IGV explícito. Este ciclo simplificado requiere revisión manual.')
        if tipo == 'pago_servicios':
            detalles = op.get('detalles')
            if not isinstance(detalles, list) or not detalles:
                raise ValueError('Falta el detalle de los servicios pagados.')
            monto = sum(moneda(item.get('monto'), 'servicio') for item in detalles)
            if op.get('monto') is not None and moneda(op['monto']) != monto:
                raise ValueError('El total leído no coincide con los servicios.')
        elif tipo == 'cobro_factura' and op.get('monto') is None:
            monto = None  # Se determina con la factura referenciada, no con la IA.
        else:
            monto = moneda(op.get('monto'), 'monto', tipo == 'inventario_final')
        if tipo == 'aporte_efectivo':
            asiento(dia, 'Por el aporte de capital en efectivo', [('10', 'debe', monto), ('50', 'haber', monto)])
        elif tipo == 'compra_mercaderia':
            pago_compra = op.get('pago') or 'contado'
            contrapartida = {'contado': '10', 'credito': '42'}.get(pago_compra)
            if not contrapartida:
                raise ValueError('La compra debe indicar contado o crédito.')
            inventario += monto
            asiento(dia, f'Por la compra de mercaderías al {pago_compra}', [('20', 'debe', monto), (contrapartida, 'haber', monto)])
        elif tipo == 'compra_activo':
            pago = {'contado': '10', 'credito': '42'}.get(op.get('pago') or 'contado')
            if not pago:
                raise ValueError('Falta la forma de pago del activo fijo.')
            asiento(dia, 'Por la adquisición de activo fijo', [('33', 'debe', monto), (pago, 'haber', monto)])
            # Solo depreciar si el caso indica vida útil y valor residual.
            if op.get('vida_util_anios') is not None:
                vida = decimal(op['vida_util_anios'], 'vida útil', Decimal('0.01'))
                residual = decimal(op.get('residual_porcentaje'), 'valor residual')
                if residual > 100:
                    raise ValueError('El valor residual no puede superar el 100%.')
                inicio = fecha(op.get('fecha_inicio_uso', op['fecha']))
                if inicio < dia:
                    raise ValueError('El inicio de uso no puede preceder a la compra.')
                activos.append((inicio, monto, vida, residual))
        elif tipo == 'venta':
            contado = decimal(op.get('porcentaje_contado'), 'porcentaje al contado')
            if contado > 100:
                raise ValueError('El porcentaje al contado no puede superar el 100%.')
            efectivo = (monto * contado / 100).quantize(CENTIMO, rounding=ROUND_HALF_UP)
            credito = monto - efectivo
            asiento(dia, 'Por la venta de mercaderías', [('10', 'debe', efectivo), ('12', 'debe', credito), ('70', 'haber', monto)])
            if credito:
                tasa = decimal(op.get('descuento_porcentaje', 0), 'descuento')
                dias = decimal(op.get('descuento_dias', 0), 'días del descuento')
                if tasa >= 100 or dias != int(dias):
                    raise ValueError('Las condiciones del descuento son inválidas.')
                facturas.append({'fecha': dia, 'saldo': credito, 'tasa': tasa, 'dias': int(dias)})
        elif tipo == 'cobro_factura':
            referencia = fecha(op.get('fecha_factura'))
            candidatas = [f for f in facturas if f['fecha'] == referencia and f['saldo'] > 0]
            if len(candidatas) != 1:
                raise ValueError('No se puede identificar de forma única la factura cobrada.')
            factura = candidatas[0]
            # El monto transcrito es el nominal de la factura, nunca el cobro neto calculado.
            if monto is None:
                monto = factura['saldo']
            if monto > factura['saldo']:
                raise ValueError('La cobranza supera el saldo de la factura.')
            transcurrido = (dia - referencia).days
            if transcurrido < 0:
                raise ValueError('El cobro no puede preceder a la factura.')
            descuento = (monto * factura['tasa'] / 100).quantize(CENTIMO, rounding=ROUND_HALF_UP) if transcurrido <= factura['dias'] else Decimal('0')
            factura['saldo'] -= monto
            asiento(dia, f'Por el cobro de factura: nominal S/ {monto:.2f}, descuento S/ {descuento:.2f}',
                    [('10', 'debe', monto - descuento), ('70', 'debe', descuento), ('12', 'haber', monto)])
        elif tipo == 'devolucion_proveedor':
            inventario -= monto
            pago = {'reembolso': '10', 'credito': '42'}.get(op.get('pago'))
            if not pago:
                raise ValueError('Indique si la devolución se reembolsa o reduce la deuda.')
            asiento(dia, 'Por la devolución de mercadería al proveedor', [(pago, 'debe', monto), ('20', 'haber', monto)])
        elif tipo == 'donacion_mercaderia':
            inventario += monto
            asiento(dia, 'Por la donación de mercadería recibida', [('20', 'debe', monto), ('75', 'haber', monto)])
        elif tipo == 'perdida_mercaderia':
            inventario -= monto
            asiento(dia, 'Por la pérdida de mercadería por siniestro', [('66', 'debe', monto), ('20', 'haber', monto)])
        elif tipo == 'sueldos_pendientes':
            asiento(dia, 'Por los gastos de personal pendientes de pago', [('62', 'debe', monto), ('41', 'haber', monto)])
        elif tipo == 'pago_servicios':
            detalles = op.get('detalles')
            if not isinstance(detalles, list) or not detalles:
                raise ValueError('Falta el detalle del pago de alquiler y servicios.')
            partidas = [('63', 'debe', moneda(item.get('monto'), 'servicio')) for item in detalles]
            if sum(m for _, _, m in partidas) != monto:
                raise ValueError('El pago no coincide con la suma de los servicios.')
            glosa = 'Por el pago de ' + ', '.join(f'{item.get("concepto", "servicio")} S/ {moneda(item["monto"]):.2f}' for item in detalles)
            asiento(dia, glosa, partidas + [('10', 'haber', monto)])
        elif tipo == 'inventario_final':
            if dia != cierre or cierre_inventario is not None:
                raise ValueError('El inventario final debe aparecer una sola vez en la fecha de cierre.')
            cierre_inventario = monto
        else:
            raise ValueError(f'Operación no soportada o ambigua: {tipo}. No se guardó ningún asiento.')
        if inventario < 0:
            raise ValueError('Las salidas de mercadería superan el inventario disponible.')

    if cierre_inventario is None:
        raise ValueError('Falta el inventario físico final para calcular el costo de ventas.')
    costo = inventario - cierre_inventario
    if costo < 0:
        raise ValueError('El inventario final supera las existencias disponibles.')
    if costo:
        asiento(cierre, f'Por el costo de ventas: existencias S/ {inventario:.2f} menos inventario final S/ {cierre_inventario:.2f}', [('69', 'debe', costo), ('20', 'haber', costo)])
    for inicio, valor, vida, residual in activos:
        # Convención mensual del taller: se cuenta el mes de puesta en uso.
        meses = max(0, (cierre.year - inicio.year) * 12 + cierre.month - inicio.month + 1)
        base = valor * (1 - residual / 100)
        depreciacion = min(base, base / (vida * 12) * meses).quantize(CENTIMO, rounding=ROUND_HALF_UP)
        if depreciacion:
            asiento(cierre, f'Por depreciación lineal de {meses} meses: costo S/ {valor:.2f}, residual {residual}%, vida útil {vida} años', [('68', 'debe', depreciacion), ('39', 'haber', depreciacion)])
    return asientos
