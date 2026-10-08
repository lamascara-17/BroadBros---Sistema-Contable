"""Orientación específica a partir del análisis y comprobaciones del borrador."""
import re
from datetime import date


def orientar_revision(datos,borrador,error=''):
    pendientes=list(borrador.get('pendientes',[]))
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
            if a.get('error_validacion'):sugerencias.append(f'Asiento {i}: {a["error_validacion"]}')
        if pendientes:sugerencias.extend(pendientes)
        elif borrador['asientos']:
            sugerencias.append('Hay una propuesta con cuentas e importes revisables. Compara cada operación con el enunciado, incluidos los pagos y cobros parciales, antes de guardar.')
    return pendientes,list(dict.fromkeys(sugerencias))
