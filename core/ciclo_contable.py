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


def normalizar_aportes(datos):
    operaciones = datos.get('operaciones', [])
    if datos.get('empresa_nueva') is True and datos.get('saldos_apertura'):
        if not isinstance(operaciones,list) or any(not isinstance(op,dict) for op in operaciones):return datos
        aportes = [op for op in operaciones if op.get('tipo') == 'aporte_efectivo']
        saldos = datos['saldos_apertura']
        # Quitar únicamente una duplicación comprobable del mismo aporte.
        if isinstance(saldos,list) and all(isinstance(x,dict) for x in saldos) and len(aportes) == 1 and len(saldos) == 2 and {x.get('concepto') for x in saldos} == {'caja', 'capital'}:
            importe = moneda(aportes[0].get('monto'))
            if all(moneda(x.get('monto')) == importe for x in saldos):
                datos = {**datos, 'saldos_apertura': []}
    return datos


def generar_asientos(datos):
    """Genera operaciones y ajustes sin deducir importes mediante un modelo."""
    if not isinstance(datos, dict) or datos.get('errores_lectura'):
        raise ValueError('La lectura contiene datos pendientes de aclarar. Use una imagen más nítida.')
    operaciones = datos.get('operaciones')
    if not isinstance(operaciones, list) or not operaciones:
        raise ValueError('No se identificaron operaciones en la imagen.')
    datos = normalizar_aportes(datos)
    if datos.get('saldos_apertura'):
        from .ciclo_documentado import generar_ciclo_documentado
        return generar_ciclo_documentado(datos)
    sin_mercaderias = not any(op.get('tipo') in ('compra_mercaderia','venta','devolucion_proveedor','donacion_mercaderia','perdida_mercaderia','inventario_final') for op in operaciones if isinstance(op,dict))
    sin_inventario = sin_mercaderias and datos.get('metodo_inventario') in (None,'sin_inventario','sin_cierre')
    if datos.get('metodo_inventario') != 'periodico' and not sin_inventario:
        raise ValueError('Esta importación requiere un caso de inventario periódico. No se guardó ningún asiento.')
    cierre = fecha(datos.get('fecha_cierre'))
    inicial = datos.get('inventario_inicial')
    if inicial is None and datos.get('empresa_nueva') is True:
        inicial = '0'
    inventario = moneda(inicial if inicial is not None or not sin_inventario else 0, 'inventario inicial', permite_cero=True)
    if inventario:
        raise ValueError('El caso contiene inventario inicial. Se requieren saldos de apertura completos; use el registro manual para este caso.')
    asientos, activos, facturas, proveedores = [], [], [], []
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

    def pago_compra(op, monto):
        if op.get('monto_pagado') is not None:
            pagado = moneda(op['monto_pagado'], 'importe pagado', permite_cero=True)
        else:
            condicion = op.get('pago') or 'contado'
            if condicion not in ('contado','credito'):
                raise ValueError('Falta el importe pagado de la compra mixta.')
            pagado = monto if condicion == 'contado' else Decimal('0')
        pendiente = monto - pagado
        if pendiente < 0:raise ValueError('El importe pagado supera el valor de la compra.')
        if op.get('monto_pendiente') is not None and moneda(op['monto_pendiente'],'saldo pendiente',permite_cero=True) != pendiente:
            raise ValueError('El valor de la compra no coincide con lo pagado y lo pendiente.')
        return pagado, pendiente

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
        if op.get('impuesto') in ('incluido','neto') or op.get('medio_pago') in ('cheque','banco'):
            raise ValueError('La operación requiere revisar sus impuestos o su cuenta bancaria.')
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
            pagado, pendiente = pago_compra(op, monto)
            inventario += monto
            if pendiente:proveedores.append({'fecha':dia,'saldo':pendiente})
            asiento(dia, 'Por la compra de mercaderías', [('20', 'debe', monto), ('10', 'haber', pagado), ('42','haber',pendiente)])
        elif tipo == 'compra_activo':
            pagado, pendiente = pago_compra(op, monto)
            if pendiente:proveedores.append({'fecha':dia,'saldo':pendiente})
            asiento(dia, 'Por la adquisición de activo fijo', [('33', 'debe', monto), ('10', 'haber', pagado), ('42','haber',pendiente)])
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
        elif tipo in ('venta','ingreso_servicios'):
            comercial = decimal(op.get('descuento_comercial_porcentaje') or 0, 'descuento comercial')
            if comercial >= 100:raise ValueError('El descuento comercial debe ser menor al 100%.')
            monto = (monto * (1 - comercial / 100)).quantize(CENTIMO, rounding=ROUND_HALF_UP)
            if op.get('monto_contado') is not None:
                efectivo = moneda(op['monto_contado'], 'importe al contado', permite_cero=True)
                if efectivo > monto:raise ValueError('El cobro al contado supera el importe neto de la venta.')
            else:
                contado = decimal(op.get('porcentaje_contado'), 'porcentaje al contado')
                if contado > 100:raise ValueError('El porcentaje al contado no puede superar el 100%.')
                efectivo = (monto * contado / 100).quantize(CENTIMO, rounding=ROUND_HALF_UP)
            credito = monto - efectivo
            if op.get('monto_pendiente') is not None and moneda(op['monto_pendiente'],'saldo por cobrar',permite_cero=True) != credito:
                raise ValueError('El ingreso no coincide con lo cobrado y lo pendiente.')
            asiento(dia, 'Por los servicios prestados' if tipo=='ingreso_servicios' else 'Por la venta de mercaderías', [('10', 'debe', efectivo), ('12', 'debe', credito), ('70', 'haber', monto)])
            if credito:
                tasa = decimal(op.get('descuento_porcentaje') or 0, 'descuento')
                if comercial and op.get('descuento_dias') is None:tasa = Decimal('0')
                dias = decimal(op.get('descuento_dias') or 0, 'días del descuento')
                if tasa >= 100 or dias != int(dias):
                    raise ValueError('Las condiciones del descuento son inválidas.')
                facturas.append({'fecha': dia, 'saldo': credito, 'tasa': tasa, 'dias': int(dias)})
        elif tipo == 'cobro_factura':
            referencia = fecha(op['fecha_factura']) if op.get('fecha_factura') else None
            candidatas = [f for f in facturas if f['saldo'] > 0 and (referencia is None or f['fecha'] == referencia)]
            if len(candidatas) != 1:
                raise ValueError('No se puede identificar de forma única la factura cobrada.')
            factura = candidatas[0]
            referencia = factura['fecha']
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
        elif tipo == 'pago_proveedor':
            referencia = fecha(op['fecha_compra']) if op.get('fecha_compra') else None
            candidatas = [f for f in proveedores if f['saldo'] > 0 and (referencia is None or f['fecha'] == referencia)]
            if len(candidatas) != 1:raise ValueError('No se puede identificar de forma única la compra pagada al proveedor.')
            compra = candidatas[0]
            deuda = sum(m['monto'] if m['tipo_movimiento']=='haber' else -m['monto'] for a in asientos for m in a['movimientos'] if m['codigo']=='42')
            if dia < compra['fecha'] or monto > compra['saldo'] or monto > deuda:
                raise ValueError('El pago al proveedor supera la deuda o precede a la compra.')
            compra['saldo'] -= monto
            asiento(dia,'Por el pago parcial de la compra a crédito',[('42','debe',monto),('10','haber',monto)])
        elif tipo == 'sueldos_mixtos':
            pagado = moneda(op.get('monto_pagado'),'sueldo pagado',permite_cero=True)
            pendiente = monto - pagado
            if pendiente < 0:raise ValueError('El sueldo pagado supera el gasto del mes.')
            if op.get('monto_pendiente') is not None and moneda(op['monto_pendiente'],'sueldo pendiente',permite_cero=True) != pendiente:
                raise ValueError('El sueldo total no coincide con lo pagado y lo pendiente.')
            asiento(dia,'Por los sueldos del mes, pagados y pendientes',[('62','debe',monto),('10','haber',pagado),('41','haber',pendiente)])
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

    if cierre_inventario is None and not sin_inventario:
        raise ValueError('Falta el inventario físico final para calcular el costo de ventas.')
    costo = inventario - (cierre_inventario if cierre_inventario is not None else 0)
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
