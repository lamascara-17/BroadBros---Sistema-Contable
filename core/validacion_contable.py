"""Controles deterministas; nunca se altera un asiento histórico para cuadrarlo."""
import re
import unicodedata
from decimal import Decimal

FUENTE_PCGE = 'https://www.mef.gob.pe/contenidos/conta_publ/documentac/PCGE_2019.pdf'


def texto(valor):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(valor).lower()) if not unicodedata.combining(c))


def grupo_esperado(nombre, tipo):
    n = texto(nombre)
    if tipo == 'activo':
        if re.search(r'\bcaja\b|\bbancos?\b|efectivo|cuenta.*corriente', n): return '10'
        if re.search(r'mercader|inventario de mercader', n): return '20'
        if re.search(r'depreciacion acumulada|amortizacion acumulada', n): return '39'
        if re.search(r'equipo|maquinaria|mobiliario', n) and not re.search(r'para.*venta|por cobrar|anticipo', n): return '33'
    if tipo == 'patrimonio' and re.fullmatch(r'capital(?: social)?', n.strip()): return '50'
    if tipo == 'ingreso' and re.search(r'\bventas\b|ingresos? por servicios|consultoria', n): return '70'
    if tipo == 'gasto' and re.search(r'costo.*ventas', n): return '69'
    return None


def validar_cuenta(codigo, nombre, tipo):
    if not re.fullmatch(r'\d{2,20}', str(codigo)):
        raise ValueError('El código de cuenta debe contener entre 2 y 20 dígitos.')
    grupo = int(str(codigo)[:2])
    compatible = (tipo == 'activo' and 10 <= grupo <= 39 or
                  tipo == 'pasivo' and 40 <= grupo <= 49 or
                  tipo == 'patrimonio' and 50 <= grupo <= 59 or
                  tipo == 'gasto' and (60 <= grupo <= 69 or grupo == 88 or 90 <= grupo <= 99) or
                  tipo == 'ingreso' and 70 <= grupo <= 79)
    esperado = grupo_esperado(nombre, tipo)
    if not compatible or esperado and not str(codigo).startswith(esperado):
        raise ValueError(f'Cuenta {codigo} — {nombre}: código incompatible con {tipo} según las familias PCGE' + (f'; corresponde revisar el grupo {esperado}.' if esperado else '.'))


def preparar_pcge(asientos):
    """Solo borradores nuevos: corrige familias reconocibles, no libros históricos."""
    from copy import deepcopy
    salida = deepcopy(asientos)
    elegidos = {}
    ocupados = {str(m.get('codigo')): (texto(m.get('nombre', '')), m.get('tipo_cuenta'))
                for a in salida for m in a.get('movimientos', [])}
    for a in salida:
        for m in a.get('movimientos', []):
            codigo = str(m.get('codigo', ''))
            nombre, tipo = m.get('nombre', ''), m.get('tipo_cuenta', '')
            grupo = grupo_esperado(nombre, tipo)
            if grupo and not codigo.startswith(grupo):
                clave = (texto(nombre), tipo)
                if clave not in elegidos:
                    base = {'10': '101', '20': '201', '33': '336', '39': '39', '50': '501', '70': '70', '69': '69'}[grupo]
                    candidato = base
                    sufijo = 1
                    while candidato in ocupados and ocupados[candidato] != clave:
                        candidato = base + str(sufijo)
                        sufijo += 1
                    elegidos[clave] = candidato
                    ocupados[candidato] = clave
                m['codigo'] = elegidos[clave]
    return salida


def importe_escrito(valor):
    n = re.sub(r'[^\d.,-]', '', valor)
    if ',' in n and '.' in n:
        decimal = ',' if n.rfind(',') > n.rfind('.') else '.'
        n = n.replace('.' if decimal == ',' else ',', '').replace(decimal, '.')
    elif ',' in n or '.' in n:
        sep = ',' if ',' in n else '.'
        partes = n.split(sep)
        n = ''.join(partes) if len(partes[-1]) == 3 else ''.join(partes[:-1]) + '.' + partes[-1]
    return Decimal(n)


def auditar_asientos(asientos, fuente=''):
    alertas = []
    saldo = Decimal('0')
    vistos = set()
    for i, a in enumerate(asientos, 1):
        movs = a['movimientos']
        glosa = texto(a.get('descripcion', ''))
        firma = (str(a.get('fecha', '')), glosa, tuple(sorted((str(m['codigo']), m['tipo_movimiento'], str(m['monto'])) for m in movs)))
        if firma in vistos:
            alertas.append(f'Asiento {i}: posible operación duplicada (misma fecha, glosa y movimientos). Aclare el documento antes de guardar.')
        vistos.add(firma)
        inventario = [m for m in movs if m['tipo_cuenta'] == 'activo' and
                      (str(m['codigo']).startswith('20') or re.search(r'mercader|inventario|existencia', texto(m['nombre'])))]
        cambio = sum((Decimal(str(m['monto'])) * (1 if m['tipo_movimiento'] == 'debe' else -1) for m in inventario), Decimal('0'))
        previo = saldo
        saldo += cambio
        if inventario and any(m['tipo_cuenta'] == 'patrimonio' for m in movs) and re.search(r'ajuste|costo.*venta|inventario.*final|inventario.*fisico', glosa):
            alertas.append(f'Asiento {i}: el ajuste de inventario afecta al capital/patrimonio. Revise costo de ventas o pérdida; no use capital para cuadrar.')
        if any(m['tipo_cuenta'] == 'patrimonio' and (str(m['codigo']).startswith('50') or re.fullmatch(r'capital(?: social)?', texto(m['nombre']).strip())) and m['tipo_movimiento'] == 'debe' for m in movs) and not re.search(r'retiro|reduccion.*capital|devolucion.*aporte|disminucion.*capital', glosa):
            alertas.append(f'Asiento {i}: disminución de capital sin retiro o reducción documentada en la glosa.')
        valores = re.findall(r'inventario[^\n.]{0,60}(?:fisico|final)[^\d\n]{0,35}([\d][\d.,]*)', glosa)
        if valores and inventario:
            fisico = importe_escrito(valores[-1])
            if fisico != saldo:
                alertas.append(f'Asiento {i}: inventario físico S/ {fisico:,.2f}, saldo contable S/ {saldo:,.2f}; diferencia S/ {saldo-fisico:,.2f}. Saldo previo S/ {previo:,.2f}; reducción neta requerida S/ {previo-fisico:,.2f}, sujeta a revisar la contrapartida.')
    n = texto(fuente)
    patrones = [r'inventario\s+(?:fisico\s+)?final[^\d\n]{0,65}([\d][\d.,]*)',
                r'inventario[^\n]{0,35}saldo\s+final[^\d\n]{0,30}([\d][\d.,]*)']
    finales = [x for patron in patrones for x in re.findall(patron, n)]
    if finales:
        fisico = importe_escrito(finales[-1])
        if saldo != fisico:
            alertas.append(f'El inventario físico del enunciado es S/ {fisico:,.2f}; los asientos dejan S/ {saldo:,.2f}. Conciliar antes de guardar.')
    return list(dict.fromkeys(alertas))
