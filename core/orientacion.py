"""Orientación específica a partir del análisis y comprobaciones del borrador."""
import re
from datetime import date


def anio_confirmado(aclaraciones):
    from .validacion_contable import texto
    for frase in re.split(r'[.;\n]',texto(aclaraciones)):
        if re.search(r'[?¿]|\b(?:no|nunca|tampoco)\b',frase): continue
        match = re.search(r'\bel ano correcto(?: del ejercicio)?\s*(?:es|:)\s*(\d{4})\b',frase)
        if match and 1900 <= int(match[1]) <= 2100: return int(match[1])
    return None


def orientar_revision(datos,borrador,error='',aclaraciones=''):
    from .notas_importacion import normalizar_notas
    pendientes=normalizar_notas(borrador.get('pendientes',[]))
    sugerencias=[]
    if datos.get('lectura_incompleta'):
        sugerencias.append('La imagen quedó cortada por el límite de tokens. Compara la lectura con el original y completa las operaciones que faltan en el campo de texto.')
    elif error:
        sugerencias.append('La lectura está conservada, pero el servicio no terminó de generar los asientos. Reintenta con esa lectura; no necesitas subir la imagen otra vez.')
    else:
        texto=datos.get('texto_leido','')
        fechas=set()
        for d,m,y in re.findall(r'(?:\bEl\s+(?:día\s+)?|(?:^|\n)\s*(?:\d+[.)]\s*)?)(\d{1,2})/(\d{1,2})/(\d{4})\b',texto,re.I):
            try:fechas.add(date(int(y),int(m),int(d)).isoformat())
            except ValueError:pass
        meses={'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,'noviembre':11,'diciembre':12}
        for d,m,y in re.findall(r'\b(?:el\s+)?día\s+(\d{1,2})\s+de\s+(\w+)\s+de(?:l)?\s+(\d{4})',texto,re.I):
            try:fechas.add(date(int(y),meses[m.lower()],int(d)).isoformat())
            except (ValueError,KeyError):pass
        fechas.update(str(op['fecha']) for op in datos.get('operaciones',[]) if isinstance(op,dict) and op.get('fecha') and op.get('tipo')!='inventario_final')
        confirmado=anio_confirmado(aclaraciones)
        encabezados=re.findall(r'\bdurante\s+(?:el\s+mes\s+de\s+)?('+'|'.join(meses)+r')\s+(?:de(?:l)?\s+)?(\d{4})\b',texto,re.I)
        if confirmado:
            fechas={f'{confirmado}{f[4:]}' for f in fechas}
        if encabezados and fechas:
            mes,ano=encabezados[0]
            esperado=confirmado or int(ano)
            incoherentes=any(int(f[:4])!=esperado for f in fechas)
            propuestos=any(re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(a.get('fecha',''))) and int(str(a['fecha'])[:4])!=esperado for a in borrador['asientos'])
            if incoherentes or propuestos:
                pendientes.append(f'El encabezado indica {mes.lower()} de {ano}, pero las fechas de las operaciones o de la propuesta no coinciden con el año {esperado}. Confirma el año con «El año correcto es {esperado}» o corrige el enunciado; no se cambia automáticamente.')
        presentes={a.get('fecha') for a in borrador['asientos']}
        for faltante in sorted(fechas-presentes):
            nota=f'Revisa la operación del {faltante}: aparece en el enunciado pero no tiene un asiento propuesto. Pide completar el análisis; no inventes un dato que ya está escrito.'
            if not any(faltante in p for p in pendientes):pendientes.append(nota)
        inventario_final = (any(isinstance(op, dict) and op.get('tipo') == 'inventario_final'
                                for op in datos.get('operaciones', [])) or
                            bool(re.search(r'inventario[^.\n]{0,100}(?:final|cierre)|saldo\s+final[^.\n]{0,60}inventario', texto, re.I)))
        venta_mercaderias = bool(re.search(r'\bventa\b|vend[eió]+\b', texto, re.I)) or any(
            isinstance(op, dict) and op.get('tipo') == 'venta' for op in datos.get('operaciones', []))
        costo_registrado = any(m.get('subcategoria') == 'costo_ventas' or
                              (m.get('tipo_cuenta') == 'gasto' and
                               ('costo de venta' in m.get('nombre', '').lower() or str(m.get('codigo', '')).startswith('69')))
                              for a in borrador['asientos'] for m in a.get('movimientos', []))
        if inventario_final and venta_mercaderias and not costo_registrado:
            nota = 'El caso incluye ventas e inventario final, pero falta el ajuste del costo de ventas. Complete el análisis usando la apertura, las compras y el inventario final indicados.'
            if nota not in pendientes: pendientes.append(nota)
        for i,a in enumerate(borrador['asientos'],1):
            if a.get('error_validacion'):
                nota=f'Asiento {i}: {a["error_validacion"]}'
                sugerencias.append(nota)
                pendientes.append(nota)
        if pendientes:sugerencias.extend(pendientes)
        elif borrador['asientos']:
            sugerencias.append('Hay una propuesta con cuentas e importes revisables. Compara cada operación con el enunciado, incluidos los pagos y cobros parciales, antes de guardar.')
    if borrador.get('asientos') and not any(a.get('error_validacion') for a in borrador['asientos']):
        from .validacion_contable import auditar_asientos
        for nota in auditar_asientos(borrador['asientos'], datos.get('texto_leido', '')):
            if nota not in pendientes: pendientes.append(nota)
            if nota not in sugerencias: sugerencias.append(nota)
    return normalizar_notas(pendientes),normalizar_notas(sugerencias)
