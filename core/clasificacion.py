"""Clasificación del activo para planes PCGE y catálogos históricos."""
import re
import unicodedata


def rubro_resultados(cuenta):
    """Respeta la clasificación explícita y los nombres de catálogos históricos."""
    sub = cuenta.subcategoria
    if cuenta.tipo == 'ingreso':
        if sub == 'otro_ingreso':
            return 'otros_ingresos'
    else:
        explicitos = {'costo_ventas': 'costo_ventas', 'gasto_operativo': 'gastos_operativos',
                      'gasto_financiero': 'gastos_financieros', 'otro_gasto': 'otros_gastos',
                      'impuesto_ganancias': 'impuesto_ganancias'}
        if sub in explicitos:
            return explicitos[sub]
    nombre = ''.join(c for c in unicodedata.normalize('NFKD', cuenta.nombre.lower())
                     if not unicodedata.combining(c))
    try:
        grupo = int(cuenta.codigo[:2])
    except ValueError:
        grupo = 0
    # Los códigos antiguos (por ejemplo 4901 y 6901) no siguen el PCGE.
    if cuenta.tipo == 'ingreso':
        otros = re.search(r'donacion|ingresos? financieros?|intereses|otros ingresos', nombre)
        return 'otros_ingresos' if otros or grupo in (73, 75, 76, 77) else 'ventas'
    if re.search(r'impuesto.*(?:ganancia|renta)', nombre):
        return 'impuesto_ganancias'
    if re.search(r'incendio|siniestro', nombre):
        return 'otros_gastos'
    if re.search(r'gastos? financieros?|intereses', nombre):
        return 'gastos_financieros'
    if re.search(r'costo.*ventas?', nombre):
        return 'costo_ventas'
    return ('impuesto_ganancias' if grupo in (87, 88) else
            'costo_ventas' if grupo == 69 else
            'gastos_financieros' if grupo == 67 else
            'otros_gastos' if grupo == 66 else 'gastos_operativos')


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
