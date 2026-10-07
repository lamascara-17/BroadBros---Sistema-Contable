"""Clasificación del activo para planes PCGE y catálogos históricos."""
import re
import unicodedata


def activo_no_corriente(codigo, nombre, subcategoria=''):
    if subcategoria in ('activo_corriente', 'activo_no_corriente'):
        return subcategoria == 'activo_no_corriente'
    texto = ''.join(c for c in unicodedata.normalize('NFD', nombre.lower()) if unicodedata.category(c) != 'Mn')
    if re.search(r'mercader|inventario|existencia|para (?:la )?venta|anticipo|adelanto|por cobrar', texto):
        return False
    if re.search(r'\b(equipos?|mobiliario|maquinaria|vehiculos?|inmuebles?|terrenos?|edificios?|depreciacion|amortizacion|intangibles?)\b', texto):
        return True
    try:return 30 <= int(codigo[:2]) <= 39
    except ValueError:return False


def fecha_cierre_del_caso(datos):
    from datetime import date
    texto = datos.get('texto_leido', '')
    literal = re.search(r'fecha\s+de\s+cierre\s*[:：]?\s*(\d{1,2})/(\d{1,2})/(\d{4})\b', texto, re.I)
    if literal:
        d, m, y = map(int, literal.groups())
        try:return date(y, m, d)
        except ValueError:raise ValueError('La fecha de cierre del ejercicio no es válida.') from None
    valor = datos.get('fecha_cierre')
    if valor:
        try:return date.fromisoformat(str(valor))
        except ValueError:raise ValueError('La fecha de cierre del ejercicio no es válida.') from None
    return None
