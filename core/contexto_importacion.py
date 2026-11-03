"""Inferencias acotadas para borradores; no modifica libros guardados."""
import re
from decimal import Decimal, InvalidOperation
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


def normalizar_operaciones_documentadas(asientos,fuente):
    """Solo corregir hechos inequívocos de un fragmento literal del enunciado.

    No modifica importes, fechas ni tipos. Casos compuestos/ambiguos permanecen
    para revisión; nunca se invierte un asiento solo para hacerlo cuadrar.
    """
    from .validacion_contable import importe_escrito
    literal=lambda s:re.sub(r'\s+',' ',nombre_normalizado(s)).strip(' .;\n')
    original=literal(fuente)
    for numero,a in enumerate(asientos,1):
        if not isinstance(a,dict):continue
        a.pop('_correcciones_backend',None)
        fragmento=literal(a.get('fuente') or '')
        if not fragmento or fragmento not in original:continue
        if re.search(r'reembolso|devoluc|reversion|anulacion|anticipo|permuta|canje|\bno (?:se )?paga|\busd\b|dolar|\beur\b',fragmento):continue
        lineas=a.get('movimientos',[])
        if not isinstance(lineas,list) or not all(isinstance(m,dict) for m in lineas):continue
        try:
            valores=[Decimal(str(m.get('monto',''))) for m in lineas]
            if not all(v.is_finite() and v>0 for v in valores):continue
        except (InvalidOperation,ValueError,TypeError):continue
        notas=[]
        efectivo=[m for m in lineas if m.get('tipo_cuenta')=='activo' and
                  (str(m.get('codigo','')).startswith('10') or re.search(r'\bcaja\b|\bbanco|efectivo',literal(m.get('nombre',''))))]
        importes={importe_escrito(v) for v in re.findall(r'\bs/\s*([\d][\d.,]*)',fragmento)}
        if len(lineas)==2 and len(efectivo)==1 and len(importes)==1 and len(set(valores))==1 and valores[0] in importes:
            caja=efectivo[0];otra=next(m for m in lineas if m is not caja)
            pago=(otra.get('tipo_cuenta')=='pasivo' and re.search(r'proveedor|deuda|prestamo',fragmento) and
                  re.search(r'\bla empresa paga\b|\bse paga[n]?\b',fragmento) and
                  not re.search(r'\bcompra\b|\badquiere\b|\badquisicion\b',fragmento))
            cobro=(otra.get('tipo_cuenta')=='activo' and
                   (str(otra.get('codigo','')).startswith(('12','13')) or re.search(r'cliente|por cobrar',literal(otra.get('nombre','')))) and
                   re.search(r'\bel cliente (?:paga|cancela)\b|\bse cobra[n]?\b',fragmento))
            if pago or cobro:
                lados=('haber','debe') if pago else ('debe','haber')
                if (caja.get('tipo_movimiento'),otra.get('tipo_movimiento'))!=lados:
                    caja['tipo_movimiento'],otra['tipo_movimiento']=lados
                    notas.append(f'Normalización del asiento {numero}: sentido del '+('pago' if pago else 'cobro')+' corregido conforme al fragmento literal y su importe, sin cambiar cifras.')
        # Un gasto se identifica por concepto E importe escritos en el texto,
        # no por el nombre arbitrario que haya elegido la IA para la cuenta.
        if (re.search(r'\bse paga[n]?\b|\bla empresa paga\b|\bse registran\b',fragmento) and
                not re.search(r'\bcliente\b|interes|financier',fragmento)):
            roles={}
            for concepto,valor in re.findall(r'\b(alquiler(?:es)?|planilla|servicios(?:\s+basicos)?)\b[^.;\n]{0,90}?\bs/\s*([\d][\d.,]*)',fragmento):
                rol=('635','Alquileres') if concepto.startswith('alquiler') else ('62','Gastos de personal') if concepto=='planilla' else ('636','Servicios básicos') if 'basicos' in concepto else ('63','Servicios de terceros')
                roles.setdefault(importe_escrito(valor),set()).add(rol)
            for m,valor in zip(lineas,valores):
                opciones=roles.get(valor,set())
                if m.get('tipo_cuenta')!='gasto' or len(opciones)!=1:continue
                codigo,nombre=next(iter(opciones))
                actual=literal(m.get('nombre',''))
                coincide=(codigo=='62' and re.search(r'personal|planilla|sueld|salari|remuneracion',actual) or
                          codigo=='635' and 'alquiler' in actual or
                          codigo.startswith('63') and codigo!='635' and 'servicio' in actual)
                if str(m.get('codigo','')).startswith(codigo) and coincide:continue
                m['codigo'],m['nombre']=codigo,nombre
                notas.append(f'Normalización del asiento {numero}: gasto identificado como {nombre} por su concepto e importe escritos en el enunciado.')
        if notas:a['_correcciones_backend']=notas
