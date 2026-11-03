"""Inferencias acotadas para borradores; no modifica libros guardados."""
import re
from .clasificacion import nombre_normalizado


INVENTARIOS = {
    '20': r'mercader',
    '21': r'productos? terminados?',
    '22': r'subproductos?|desechos?|residuos?',
    '23': r'productos? en proceso',
    '24': r'materias? primas?',
    '25': r'materiales? auxiliares?|suministros?|repuestos?',
    '26': r'envases?|embalajes?',
}


def familias_inventario(texto):
    n=nombre_normalizado(texto)
    return {grupo for grupo,patron in INVENTARIOS.items() if re.search(patron,n)}


def inventario_generico(nombre):
    return bool(re.fullmatch(r'(?:inventarios?|existencias)(?: de almacen)?',nombre_normalizado(nombre).strip()))


def familia_del_inventario(asiento, fuente=''):
    globales=familias_inventario(fuente)
    locales=familias_inventario(asiento.get('descripcion','')+' '+asiento.get('fuente',''))
    literal=lambda s:re.sub(r'\s+',' ',nombre_normalizado(s)).strip()
    respaldo=any(literal(asiento.get(k,'')) and literal(asiento.get(k,'')) in literal(fuente)
                 for k in ('fuente','descripcion'))
    if len(locales)==1 and (not fuente or len(globales)==1 and locales <= globales or respaldo):return next(iter(locales))
    if len(globales)==1:return next(iter(globales))
    return None


def es_ajuste_de_cierre(asiento):
    lineas=asiento.get('movimientos',[])
    gasto=any(m.get('tipo_cuenta')=='gasto' and
              (str(m.get('codigo','')).startswith(('68','69')) or
               re.search(r'depreciacion|amortizacion|costo.*venta',nombre_normalizado(m.get('nombre','')))) for m in lineas)
    contrapartida=any(m.get('tipo_cuenta')=='activo' and
                     (str(m.get('codigo','')).startswith(('20','21','22','23','24','25','26','39')) or
                      re.search(r'inventario|existencia|acumulad',nombre_normalizado(m.get('nombre','')))) for m in lineas)
    return gasto and contrapartida
