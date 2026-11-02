from .models import CuentaContable, AsientoContable, Movimiento, RespaldoCaso
from django.db import transaction


def serializar_caso():
    anteriores = list(AsientoContable.objects.prefetch_related('movimientos__cuenta'))
    catalogo = list(CuentaContable.objects.values('codigo', 'nombre', 'tipo', 'subcategoria'))
    datos = [{'fecha': str(a.fecha), 'descripcion': a.descripcion, 'clase': a.clase,
              'flujo_efectivo': a.flujo_efectivo, 'fecha_cierre': str(a.fecha_cierre_ejercicio) if a.fecha_cierre_ejercicio else None,
              'fuente': a.fuente_importacion, 'observaciones': a.observaciones_importacion,
              'movimientos': [{'codigo': m.cuenta.codigo, 'nombre': m.cuenta.nombre, 'tipo_cuenta': m.cuenta.tipo,
                  'subcategoria': m.cuenta.subcategoria, 'tipo_movimiento': m.tipo, 'monto': str(m.monto)} for m in a.movimientos.all()]} for a in anteriores]
    return {'formato':'BROADBROS', 'version':1, 'asientos':datos, 'cuentas':catalogo}


def crear_respaldo():
    contenido = serializar_caso()
    if not contenido['asientos'] and not contenido['cuentas']: return None
    return RespaldoCaso.objects.create(datos=contenido['asientos'], catalogo=contenido['cuentas'])


def restaurar(respaldo):
    from .importacion_general import validar_asientos
    # Se validan estructura y partida doble, sin renumerar el catálogo histórico.
    for inicio in range(0, len(respaldo.datos), 100):
        validar_asientos(respaldo.datos[inicio:inicio+100])
    with transaction.atomic():
        crear_respaldo()
        AsientoContable.objects.all().delete()
        CuentaContable.objects.all().delete()
        cuentas = {r['codigo']: CuentaContable.objects.create(**r) for r in respaldo.catalogo}
        for r in respaldo.datos:
            a = AsientoContable.objects.create(fecha=r['fecha'], descripcion=r['descripcion'], clase=r['clase'],
                flujo_efectivo=r['flujo_efectivo'], fecha_cierre_ejercicio=r.get('fecha_cierre'),
                fuente_importacion=r.get('fuente',''), observaciones_importacion=r.get('observaciones',''))
            for m in r['movimientos']:
                if m['codigo'] not in cuentas:
                    cuentas[m['codigo']] = CuentaContable.objects.create(codigo=m['codigo'], nombre=m['nombre'], tipo=m['tipo_cuenta'], subcategoria=m.get('subcategoria',''))
                Movimiento.objects.create(asiento=a, cuenta=cuentas[m['codigo']], tipo=m['tipo_movimiento'], monto=m['monto'])


def validar_respaldo(contenido):
    """Formato portable acotado, sin IDs de usuario/workspace ni campos arbitrarios."""
    from datetime import date
    from .importacion_general import validar_asientos
    if not isinstance(contenido, dict) or set(contenido) - {'formato', 'version', 'asientos', 'cuentas'}:
        raise ValueError('El respaldo debe contener asientos y cuentas de BROADBROS.')
    if type(contenido.get('version', 1)) is not int or contenido.get('version', 1) != 1 or contenido.get('formato', 'BROADBROS') != 'BROADBROS':
        raise ValueError('Versión o formato de respaldo no compatible.')
    entradas, catalogo = contenido.get('asientos'), contenido.get('cuentas')
    if not isinstance(entradas, list) or not isinstance(catalogo, list) or len(catalogo) > 1000 or len(entradas) > 1000:
        raise ValueError('El respaldo admite hasta 1 000 asientos y 1 000 cuentas.')
    cuentas = {}
    permitidos = {'codigo','nombre','tipo','subcategoria'}
    for c in catalogo:
        if not isinstance(c, dict) or set(c) - permitidos:
            raise ValueError('La cuenta del respaldo contiene campos no permitidos.')
        codigo, nombre, tipo, sub = (c.get('codigo'), c.get('nombre'), c.get('tipo'), c.get('subcategoria', ''))
        import re
        if not isinstance(codigo,str) or not re.fullmatch(r'\d{2,20}', codigo) or not isinstance(nombre,str) or not nombre.strip() or len(nombre)>200:
            raise ValueError('Código o nombre de cuenta inválido en el respaldo.')
        if not isinstance(tipo,str) or not isinstance(sub,str) or tipo not in dict(CuentaContable.TIPO_CHOICES) or sub not in dict(CuentaContable.SUBCATEGORIA_CHOICES) or codigo in cuentas:
            raise ValueError('Clasificación de cuenta inválida o código repetido en el respaldo.')
        cuentas[codigo] = {'codigo':codigo,'nombre':nombre,'tipo':tipo,'subcategoria':sub}
    try:
        validos = [a for inicio in range(0, len(entradas), 100) for a in validar_asientos(entradas[inicio:inicio+100])]
    except (TypeError, AttributeError, ArithmeticError):
        raise ValueError('El respaldo contiene datos de asiento inválidos.') from None
    salida=[]
    for original, asiento in zip(entradas,validos):
        if set(original) - {'fecha','descripcion','clase','flujo_efectivo','fecha_cierre','fuente','observaciones','movimientos'}:
            raise ValueError('El asiento contiene campos no permitidos.')
        fuente, obs = original.get('fuente',''), original.get('observaciones','')
        if not isinstance(fuente,str) or len(fuente)>20000 or not isinstance(obs,str) or len(obs)>10000:
            raise ValueError('La lectura o las observaciones del respaldo exceden el tamaño permitido.')
        cierre=original.get('fecha_cierre')
        if cierre is not None:
            try: cierre=date.fromisoformat(cierre).isoformat()
            except (ValueError, TypeError): raise ValueError('Fecha de cierre inválida en el respaldo.') from None
            if validos and cierre < max(str(a['fecha']) for a in validos):
                raise ValueError('La fecha de cierre del respaldo precede a sus operaciones.')
        for raw, m in zip(original['movimientos'], asiento['movimientos']):
            if set(raw) - {'codigo','nombre','tipo_cuenta','subcategoria','tipo_movimiento','monto'}:
                raise ValueError('El movimiento contiene campos no permitidos.')
            c=cuentas.get(m['codigo'])
            if not c or (c['nombre'],c['tipo'],c['subcategoria']) != (m['nombre'],m['tipo_cuenta'],m['subcategoria']):
                raise ValueError('Los movimientos no coinciden con el catálogo del respaldo.')
            m['monto']=str(m['monto'])
        salida.append({'fecha':str(asiento['fecha']),'descripcion':asiento['descripcion'],
                       'clase':asiento['clase'],'flujo_efectivo':asiento['flujo_efectivo'],
                       'fecha_cierre':cierre,'fuente':fuente,'observaciones':obs,'movimientos':asiento['movimientos']})
    return salida, list(cuentas.values())
