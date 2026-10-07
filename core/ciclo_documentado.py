"""Apertura, IVA y letras: importes calculados, no generados por la IA."""
from decimal import Decimal, ROUND_HALF_UP
from .ciclo_contable import CUENTAS, CENTIMO, decimal, moneda, fecha

CUENTAS_DOCUMENTADAS = {
    **CUENTAS,
    '101': ('Caja', 'activo', ''),
    '1041': ('Cuentas corrientes operativas', 'activo', ''),
    '121': ('Facturas por cobrar', 'activo', ''),
    '123': ('Letras por cobrar', 'activo', ''),
    '4011': ('IGV / IVA - débito y crédito fiscal', 'pasivo', ''),
    '421': ('Facturas por pagar a proveedores', 'pasivo', ''),
    '423': ('Letras por pagar', 'pasivo', ''),
}
APERTURA = {'caja': ('101', 'debe'), 'banco': ('1041', 'debe'),
            'clientes': ('121', 'debe'), 'mercaderias': ('20', 'debe'),
            'proveedores': ('421', 'haber'), 'capital': ('50', 'haber')}


def entero(valor, campo):
    n = decimal(valor, campo, Decimal('1'))
    if n != int(n) or n > 1000:
        raise ValueError(f'{campo} debe ser un entero entre 1 y 1000.')
    return int(n)


def generar_ciclo_documentado(datos):
    operaciones = datos['operaciones']
    cierre = fecha(datos.get('fecha_cierre'))
    if any(not isinstance(op, dict) for op in operaciones):
        raise ValueError('La lectura de operaciones está incompleta.')
    orden = sorted(operaciones, key=lambda op: fecha(op.get('fecha')))
    apertura_fecha = fecha(datos.get('fecha_apertura') or orden[0]['fecha'])
    if apertura_fecha > fecha(orden[0]['fecha']) or cierre < fecha(orden[-1]['fecha']):
        raise ValueError('Las fechas de apertura, operaciones y corte son inconsistentes.')
    if datos.get('metodo_inventario') not in (None, 'sin_cierre'):
        raise ValueError('El ciclo con saldos de apertura admite operaciones sin ajuste de inventario; revise el cierre por separado.')
    asientos, lotes_cobrar, lotes_pagar = [], [], []
    saldos = {}

    def asiento(dia, descripcion, lineas):
        lineas = [(c, t, m) for c, t, m in lineas if m]
        if len(lineas) < 2 or sum(m for _, t, m in lineas if t == 'debe') != sum(m for _, t, m in lineas if t == 'haber'):
            raise ValueError('El asiento no cumple la partida doble; revise los saldos de apertura.')
        movimientos = []
        for c, t, m in lineas:
            moneda(m)
            nombre, tipo, subcategoria = CUENTAS_DOCUMENTADAS[c]
            movimientos.append({'codigo': c, 'nombre': nombre, 'tipo_cuenta': tipo,
                                'subcategoria': subcategoria, 'tipo_movimiento': t, 'monto': m})
            saldos[c] = saldos.get(c, Decimal('0')) + (m if t == 'debe' else -m)
        for c in ('101', '1041', '121', '123', '20'):
            if saldos.get(c, 0) < 0:
                raise ValueError(f'La operación supera el saldo disponible de la cuenta {c}.')
        asientos.append({'fecha': dia, 'descripcion': descripcion, 'movimientos': movimientos})

    saldos_apertura = datos['saldos_apertura']
    if not isinstance(saldos_apertura, list) or not saldos_apertura:
        raise ValueError('Faltan los saldos de apertura completos.')
    vistos, lineas = set(), []
    for item in saldos_apertura:
        if not isinstance(item, dict) or item.get('concepto') not in APERTURA or item['concepto'] in vistos:
            raise ValueError('Una cuenta de apertura es desconocida o está duplicada.')
        concepto = item['concepto']; vistos.add(concepto)
        c, t = APERTURA[concepto]
        lineas.append((c, t, moneda(item.get('monto'), 'saldo inicial', permite_cero=True)))
    deuda_inicial = -sum(m if t == 'debe' else -m for c, t, m in lineas if c == '421')
    asiento(apertura_fecha, 'Por los saldos de apertura del ejercicio', lineas)

    def medio(op):
        cuenta = {'efectivo': '101', 'cheque': '1041', 'banco': '1041'}.get(op.get('medio_pago'))
        if not cuenta:
            raise ValueError('Falta indicar si el movimiento se realiza en efectivo, banco o cheque.')
        return cuenta

    def importes(op):
        monto = moneda(op.get('monto'))
        estado = op.get('impuesto')
        if estado == 'no_indicado':
            return monto, Decimal('0'), monto
        if estado not in ('incluido', 'neto'):
            raise ValueError('Falta indicar si el impuesto está incluido o el importe es neto.')
        tasa = decimal(op.get('tasa_impuesto') if op.get('tasa_impuesto') is not None else datos.get('tasa_impuesto_configurada'), 'tasa de IVA/IGV')
        if tasa > 100:
            raise ValueError('La tasa de IVA/IGV no puede superar el 100%.')
        if estado == 'incluido':
            base = (monto / (1 + tasa / 100)).quantize(CENTIMO, rounding=ROUND_HALF_UP)
            return base, monto - base, monto
        impuesto = (monto * tasa / 100).quantize(CENTIMO, rounding=ROUND_HALF_UP)
        return monto, impuesto, monto + impuesto

    def lote(op, total, lotes):
        cantidad = entero(op.get('numero_letras'), 'número de letras')
        numeros = op.get('letras_numeros')
        if numeros is not None:
            if not isinstance(numeros, list) or len(numeros) != cantidad or len(set(map(str, numeros))) != cantidad:
                raise ValueError('Los números de las letras no coinciden con su cantidad.')
            numeros = list(map(str, numeros))
        if op.get('letras_importes') is not None:
            importes_letras = op['letras_importes']
            if not isinstance(importes_letras, list) or len(importes_letras) != cantidad:
                raise ValueError('Faltan los importes individuales de las letras.')
            importes_letras = [moneda(m, 'letra') for m in importes_letras]
            if sum(importes_letras) != total:
                raise ValueError('Las letras no suman el importe documentado.')
        else:
            # Convención mostrada en el formulario: cuotas iguales, residuo en la última.
            cuota = (total / cantidad).quantize(CENTIMO, rounding=ROUND_HALF_UP)
            importes_letras = [cuota] * (cantidad - 1) + [total - cuota * (cantidad - 1)]
            for m in importes_letras: moneda(m, 'letra')
        contraparte = str(op.get('contraparte') or '').strip().casefold()
        if not contraparte:
            raise ValueError('Falta identificar al cliente o proveedor de las letras.')
        lotes.append({'contraparte': contraparte, 'fecha': fecha(op['fecha']),
                      'numeros': numeros, 'importes': importes_letras, 'pagadas': set(),
                      'cuotas_uniformes': op.get('letras_importes') is None})

    def liquidar(op, lotes, dia):
        contraparte = str(op.get('contraparte') or '').strip().casefold()
        candidatos = [l for l in lotes if l['contraparte'] == contraparte and len(l['pagadas']) < len(l['importes'])]
        if op.get('fecha_documento'):
            candidatos = [l for l in candidatos if l['fecha'] == fecha(op['fecha_documento'])]
        numeros = op.get('letras_numeros')
        if numeros is not None:
            if not isinstance(numeros, list) or not numeros or len(set(map(str, numeros))) != len(numeros):
                raise ValueError('Las letras a liquidar están duplicadas o incompletas.')
            candidatos = [l for l in candidatos if l['numeros'] is not None and set(map(str, numeros)).issubset(l['numeros'])]
        if len(candidatos) != 1:
            raise ValueError('No se puede identificar de forma única el lote de letras.')
        l = candidatos[0]
        if dia < l['fecha']:
            raise ValueError('El pago no puede preceder a la emisión de las letras.')
        if numeros is not None:
            indices = [l['numeros'].index(str(n)) for n in numeros]
            if any(i in l['pagadas'] for i in indices):
                raise ValueError('Una de las letras ya fue liquidada.')
        else:
            cantidad = entero(op.get('cantidad_letras'), 'cantidad de letras a liquidar')
            indices = [i for i in range(len(l['importes'])) if i not in l['pagadas']][:cantidad]
            if len(indices) != cantidad:
                raise ValueError('La cantidad solicitada supera las letras pendientes.')
            if not l['cuotas_uniformes'] and len(set(l['importes'][i] for i in range(len(l['importes'])) if i not in l['pagadas'])) > 1:
                raise ValueError('Las letras tienen importes diferentes: indique sus números para liquidarlas.')
        monto = sum(l['importes'][i] for i in indices)
        if op.get('monto') is not None and moneda(op['monto']) != monto:
            raise ValueError('El importe indicado no coincide con las letras seleccionadas.')
        l['pagadas'].update(indices)
        return monto

    for op in orden:
        if not str(op.get('texto') or '').strip():
            raise ValueError('Falta el texto original de una operación.')
        dia = fecha(op['fecha']); tipo = op.get('tipo')
        if tipo == 'compra_mercaderia':
            base, impuesto, total = importes(op)
            pago = op.get('pago')
            if pago == 'letras':
                lote(op, total, lotes_pagar); cuenta = '423'
            elif pago == 'credito': cuenta = '421'
            elif pago == 'contado': cuenta = medio(op)
            else: raise ValueError('Falta la modalidad de pago de la compra.')
            asiento(dia, 'Por la compra de mercaderías' + (' documentada con letras' if pago == 'letras' else ''),
                    [('20', 'debe', base), ('4011', 'debe', impuesto), (cuenta, 'haber', total)])
        elif tipo == 'venta':
            base, impuesto, total = importes(op)
            porcentaje = decimal(op.get('porcentaje_contado'), 'porcentaje al contado')
            if porcentaje > 100: raise ValueError('El porcentaje al contado supera el 100%.')
            if op.get('descuento_porcentaje') not in (None, 0, '0'):
                raise ValueError('Los descuentos en ventas con IVA requieren revisión manual.')
            efectivo = (total * porcentaje / 100).quantize(CENTIMO, rounding=ROUND_HALF_UP)
            credito = total - efectivo
            if credito and op.get('saldo_documentado') is True:
                lote(op, credito, lotes_cobrar); cuenta = '123'
            elif credito and op.get('saldo_documentado') is False: cuenta = '121'
            elif credito: raise ValueError('Falta indicar si el saldo de la venta está documentado con letras.')
            else: cuenta = '121'
            lineas = [(medio(op), 'debe', efectivo)] if efectivo else []
            asiento(dia, 'Por la venta de mercaderías y su impuesto', lineas +
                    [(cuenta, 'debe', credito), ('70', 'haber', base), ('4011', 'haber', impuesto)])
        elif tipo == 'pago_servicios':
            if op.get('impuesto') != 'no_indicado':
                raise ValueError('El pago de servicios con impuesto explícito requiere revisión manual.')
            detalles = op.get('detalles')
            if not isinstance(detalles, list) or not detalles: raise ValueError('Falta el detalle del servicio.')
            total = sum(moneda(d.get('monto'), 'servicio') for d in detalles)
            if op.get('monto') is not None and moneda(op['monto']) != total:
                raise ValueError('El total no coincide con los servicios.')
            asiento(dia, 'Por el pago de ' + ', '.join(str(d.get('concepto', 'servicio')) for d in detalles),
                    [('63', 'debe', total), (medio(op), 'haber', total)])
        elif tipo == 'pago_proveedor_inicial':
            porcentaje = decimal(op.get('porcentaje'), 'porcentaje de la deuda inicial')
            if porcentaje > 100: raise ValueError('El porcentaje supera la deuda inicial.')
            monto = moneda((deuda_inicial * porcentaje / 100).quantize(CENTIMO, rounding=ROUND_HALF_UP))
            if op.get('monto') is not None and moneda(op['monto']) != monto:
                raise ValueError('El pago no coincide con el porcentaje de la deuda inicial.')
            if monto > -saldos.get('421', 0): raise ValueError('El pago supera la deuda con proveedores.')
            asiento(dia, 'Por el pago parcial de proveedores del inventario inicial', [('421', 'debe', monto), (medio(op), 'haber', monto)])
        elif tipo in ('cobro_letras', 'pago_letras'):
            cobro = tipo == 'cobro_letras'
            monto = liquidar(op, lotes_cobrar if cobro else lotes_pagar, dia)
            cuenta = '123' if cobro else '423'; banco = medio(op)
            lineas = [(banco, 'debe', monto), (cuenta, 'haber', monto)] if cobro else [(cuenta, 'debe', monto), (banco, 'haber', monto)]
            asiento(dia, 'Por el ' + ('cobro' if cobro else 'pago') + ' de letras de ' + str(op['contraparte']), lineas)
        else:
            raise ValueError(f'Operación fuera del ciclo documentado soportado: {tipo}.')
    return asientos
