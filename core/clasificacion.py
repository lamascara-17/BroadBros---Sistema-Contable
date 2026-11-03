"""Clasificación del activo para planes PCGE y catálogos históricos."""
import re
import unicodedata


def nombre_normalizado(nombre):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(nombre).lower())
                   if not unicodedata.combining(c))


def ingreso_no_ordinario(nombre):
    """No confundir la venta de un activo de uso con ventas del giro."""
    return bool(re.search(
        r'donacion|intereses|financier|dividend|otros ingresos|enajenacion|'
        r'activos? (?:fijos?|inmovilizados?)|(?:ganancia|utilidad|perdida) por venta|'
        r'comision|corretaje|pronto pago', nombre_normalizado(nombre)))


def venta_ordinaria(nombre):
    n = nombre_normalizado(nombre)
    if ingreso_no_ordinario(n) or re.search(r'descuento|rebaja|bonificacion', n):
        return False
    return bool(re.search(r'\bventas?\b|ingresos? (?:por|de) (?:servicios|actividades ordinarias)|'
                          r'prestacion de servicios|servicios prestados|consultoria', n))


def rubro_resultados(cuenta):
    """Las ventas identificadas no se convierten en otros ingresos por una etiqueta.

    Lee catálogos históricos sin cambiar sus cuentas ni sus movimientos.
    Las devoluciones y descuentos comerciales conservan su saldo con signo.
    """
    sub = cuenta.subcategoria
    nombre = nombre_normalizado(cuenta.nombre)
    try:
        grupo = int(cuenta.codigo[:2])
    except ValueError:
        grupo = 0
    if cuenta.tipo == 'ingreso':
        if not ingreso_no_ordinario(nombre) and (grupo in (70, 74) or venta_ordinaria(nombre)):
            return 'ventas'
        if sub == 'otro_ingreso':
            return 'otros_ingresos'
    else:
        explicitos = {'costo_ventas': 'costo_ventas', 'gasto_operativo': 'gastos_operativos',
                      'gasto_financiero': 'gastos_financieros', 'otro_gasto': 'otros_gastos',
                      'impuesto_ganancias': 'impuesto_ganancias'}
        if sub in explicitos:
            return explicitos[sub]
    # Los códigos antiguos (por ejemplo 4901 y 6901) no siguen el PCGE.
    if cuenta.tipo == 'ingreso':
        return 'otros_ingresos' if ingreso_no_ordinario(nombre) or grupo in (71, 72, 73, 75, 76, 77, 78) else 'ventas'
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
    from calendar import monthrange
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
    n=nombre_normalizado(texto)
    if re.search(r'(?:al cierre|al final|al termino) del mes',n):
        periodos=set()
        for d,m,y in re.findall(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b',n):
            try:
                f=date(int(y),int(m),int(d));periodos.add((f.year,f.month))
            except ValueError:return None
        meses={'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,'noviembre':11,'diciembre':12}
        for mes,y in re.findall(r'\b('+'|'.join(meses)+r')\s+(?:de(?:l)?\s+)?(\d{4})\b',n):
            periodos.add((int(y),meses[mes]))
        for op in datos.get('operaciones',[]):
            if isinstance(op,dict) and op.get('fecha'):
                try:
                    f=date.fromisoformat(str(op['fecha']));periodos.add((f.year,f.month))
                except ValueError:return None
        if len(periodos)==1:
            y,m=next(iter(periodos));return date(y,m,monthrange(y,m)[1])
    return None
