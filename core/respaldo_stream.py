"""JSON v1 con archivos temporales, validación por asiento y bloques en BD.

Los temporales solo duran una petición. Las copias duraderas siguen en la misma
base de datos del visitante, sin depender del disco efímero del servidor.
"""
import json
from tempfile import TemporaryFile
from django.db import transaction
import ijson
from .models import AsientoContable, CuentaContable, Movimiento, RespaldoCaso, RespaldoFragmento
from .consultas import movimientos_con_cuentas

BLOQUE = 64 * 1024
ENCODER = json.JSONEncoder(ensure_ascii=False, separators=(',', ':'), allow_nan=False, sort_keys=True)


def escribir_json(archivo, objeto):
    for texto in ENCODER.iterencode(objeto):
        archivo.write(texto.encode('utf-8'))


def escribir_caso(archivo, asientos, catalogo):
    # PostgreSQL JSONB no conserva el orden de claves; el formato portable sí
    # fija ese orden para obtener una copia reproducible en ambos motores.
    archivo.write(b'{"formato":"BROADBROS","version":1,"asientos":[')
    for i, asiento in enumerate(asientos):
        if i: archivo.write(b',')
        escribir_json(archivo, asiento)
    archivo.write(b'],"cuentas":[')
    for i, cuenta in enumerate(catalogo):
        if i: archivo.write(b',')
        escribir_json(archivo, cuenta)
    archivo.write(b']}')


def serializar_asiento(a):
    return {'fecha': str(a.fecha), 'descripcion': a.descripcion, 'clase': a.clase,
        'flujo_efectivo': a.flujo_efectivo,
        'fecha_cierre': str(a.fecha_cierre_ejercicio) if a.fecha_cierre_ejercicio else None,
        'fuente': a.fuente_importacion, 'observaciones': a.observaciones_importacion,
        'movimientos': [{'codigo': m.cuenta.codigo, 'nombre': m.cuenta.nombre, 'tipo_cuenta': m.cuenta.tipo,
            'subcategoria': m.cuenta.subcategoria, 'tipo_movimiento': m.tipo, 'monto': str(m.monto)}
            for m in a.movimientos.all()]}


def archivo_actual():
    from .contexto_bot import firma_caso
    firma = firma_caso()
    archivo = TemporaryFile(mode='w+b')
    try:
        asientos = AsientoContable.objects.prefetch_related(movimientos_con_cuentas()).iterator(chunk_size=10)
        catalogo = CuentaContable.objects.values('codigo','nombre','tipo','subcategoria').iterator(chunk_size=100)
        escribir_caso(archivo, (serializar_asiento(a) for a in asientos), catalogo)
        validar_archivo(archivo)
        if firma_caso() != firma:
            raise ValueError('El caso cambió al preparar la copia. Descárgala nuevamente.')
        archivo.seek(0)
        return archivo
    except BaseException:
        archivo.close()
        raise


def archivo_historico(respaldo, validar=True):
    archivo = TemporaryFile(mode='w+b')
    try:
        if respaldo.fragmentos.exists():
            for bloque in respaldo.fragmentos.values_list('contenido', flat=True).iterator(chunk_size=1):
                archivo.write(bytes(bloque))
        else:
            catalogo = respaldo.catalogo
            if not catalogo and respaldo.datos:
                # Copias anteriores a 0009: el catálogo estaba solo en las líneas.
                cuentas = {}
                for asiento in respaldo.datos:
                    for m in asiento.get('movimientos', []):
                        c = {'codigo':m['codigo'], 'nombre':m['nombre'], 'tipo':m['tipo_cuenta'],
                            'subcategoria':m.get('subcategoria','')}
                        if c['codigo'] in cuentas and cuentas[c['codigo']] != c:
                            raise ValueError('El catálogo histórico contiene clasificaciones contradictorias.')
                        cuentas[c['codigo']] = c
                catalogo = list(cuentas.values())
            escribir_caso(archivo, respaldo.datos, catalogo)
        if validar:
            validar_archivo(archivo)
        archivo.seek(0)
        return archivo
    except BaseException:
        archivo.close()
        raise


def proteger_parser(archivo):
    """Limita escalares y profundidad ANTES de que el parser reserve memoria."""
    from .respaldos import MAX_RESPALDO_BYTES
    archivo.seek(0)
    cadena = escape = False
    longitud = profundidad = total = token = 0
    while bloque := archivo.read(BLOQUE):
        total += len(bloque)
        if total > MAX_RESPALDO_BYTES:
            raise ValueError('El respaldo supera los 256 MiB permitidos.')
        for b in bloque:
            if cadena:
                longitud += 1
                if longitud > 200000:
                    raise ValueError('Un campo del respaldo excede el tamaño permitido.')
                if escape: escape = False
                elif b == 92: escape = True
                elif b == 34: cadena = False
            elif b == 34:
                cadena, longitud, token = True, 0, 0
            elif b in (91, 123):
                profundidad += 1
                if profundidad > 12: raise ValueError('El respaldo tiene demasiados niveles.')
                token = 0
            elif b in (93, 125):
                profundidad -= 1
                token = 0
            elif b in (32, 9, 10, 13, 44, 58): token = 0
            else:
                token += 1
                if token > 100: raise ValueError('Número o token demasiado largo en el respaldo.')
    archivo.seek(0)


def items(archivo, prefijo):
    archivo.seek(0)
    yield from ijson.items(archivo, prefijo)


def validar_archivo(archivo):
    from .respaldos import validar_respaldo, MAX_CUENTAS_RESPALDO, MAX_ASIENTOS_RESPALDO
    proteger_parser(archivo)
    try:
        claves = set()
        campos = {
            '': {'formato','version','asientos','cuentas'},
            'cuentas.item': {'codigo','nombre','tipo','subcategoria'},
            'asientos.item': {'fecha','descripcion','clase','flujo_efectivo','fecha_cierre','fuente','observaciones','movimientos'},
            'asientos.item.movimientos.item': {'codigo','nombre','tipo_cuenta','subcategoria','tipo_movimiento','monto'},
        }
        largos = {'fuente':20000,'observaciones':10000,'descripcion':2000,'nombre':200,
            'codigo':20,'fecha':10,'fecha_cierre':10,'tipo':20,'tipo_cuenta':20,
            'subcategoria':20,'clase':12,'flujo_efectivo':12,'tipo_movimiento':5,'monto':100,'formato':9}
        archivo.seek(0)
        inicio = True
        objetos = []
        contador_asientos = contador_cuentas = movimientos = 0
        for prefijo, evento, valor in ijson.parse(archivo):
            if inicio:
                if (prefijo, evento) != ('', 'start_map'): raise ValueError('El respaldo debe ser un objeto JSON.')
                inicio = False
            if evento == 'string' and len(valor) > largos.get(prefijo.rsplit('.',1)[-1], 200):
                raise ValueError('Un campo del respaldo excede el tamaño permitido.')
            if evento == 'map_key' and valor not in campos.get(prefijo, set()):
                raise ValueError('Campo no permitido en esta parte del respaldo.')
            if prefijo in ('asientos.item', 'cuentas.item', 'asientos.item.movimientos.item') and evento not in ('start_map', 'map_key', 'end_map'):
                raise ValueError('Cada cuenta, asiento y movimiento debe ser un objeto.')
            if evento == 'start_map':
                if prefijo not in ('', 'asientos.item', 'cuentas.item', 'asientos.item.movimientos.item'):
                    raise ValueError('Objeto inesperado en el respaldo.')
                objetos.append(set())
                if prefijo == 'asientos.item':
                    contador_asientos += 1
                    movimientos = 0
                    if contador_asientos > MAX_ASIENTOS_RESPALDO: raise ValueError('El respaldo admite hasta 1 000 asientos.')
                elif prefijo == 'cuentas.item':
                    contador_cuentas += 1
                    if contador_cuentas > MAX_CUENTAS_RESPALDO: raise ValueError('El respaldo admite hasta 1 000 cuentas.')
                elif prefijo == 'asientos.item.movimientos.item':
                    movimientos += 1
                    if movimientos > 40: raise ValueError('Un asiento admite hasta 40 movimientos.')
            elif evento == 'end_map': objetos.pop()
            elif evento == 'map_key':
                if valor in objetos[-1]: raise ValueError('Campo repetido en el respaldo.')
                objetos[-1].add(valor)
            elif evento == 'start_array' and prefijo not in ('asientos', 'cuentas', 'asientos.item.movimientos'):
                raise ValueError('Lista inesperada en el respaldo.')
            if prefijo == '' and evento == 'map_key':
                if valor in claves or valor not in {'formato','version','asientos','cuentas'}:
                    raise ValueError('Campo desconocido o repetido en el respaldo.')
                claves.add(valor)
            if prefijo == 'version' and (evento != 'number' or type(valor) is not int or valor != 1):
                raise ValueError('Versión del respaldo no compatible.')
            if prefijo == 'formato' and (evento != 'string' or valor != 'BROADBROS'):
                raise ValueError('Formato de respaldo no compatible.')
            if prefijo in ('asientos','cuentas') and evento not in ('start_array','end_array'):
                raise ValueError('Los asientos y cuentas deben ser listas.')
            # Un objeto individual no puede crecer sin límite antes de validar.
            if evento == 'map_key' and valor not in {'formato','version','asientos','cuentas','fecha','descripcion','clase',
                    'flujo_efectivo','fecha_cierre','fuente','observaciones','movimientos','codigo','nombre','tipo',
                    'tipo_cuenta','subcategoria','tipo_movimiento','monto'}:
                raise ValueError('Campo no permitido en el respaldo.')
        if not {'asientos','cuentas'} <= claves: raise ValueError('Faltan asientos o cuentas en el respaldo.')
        catalogo = []
        for c in items(archivo, 'cuentas.item'):
            catalogo.append(c)
            if len(catalogo) > MAX_CUENTAS_RESPALDO: raise ValueError('El respaldo admite hasta 1 000 cuentas.')
        validar_respaldo({'asientos':[], 'cuentas':catalogo})
        cantidad, ultima, cierre_minimo = 0, None, None
        for a in items(archivo, 'asientos.item'):
            cantidad += 1
            if cantidad > MAX_ASIENTOS_RESPALDO: raise ValueError('El respaldo admite hasta 1 000 asientos.')
            datos, _ = validar_respaldo({'asientos':[a], 'cuentas':catalogo})
            fila = datos[0]
            ultima = max(ultima or fila['fecha'], fila['fecha'])
            if fila['fecha_cierre']: cierre_minimo = min(cierre_minimo or fila['fecha_cierre'], fila['fecha_cierre'])
        if cierre_minimo and ultima and cierre_minimo < ultima:
            raise ValueError('La fecha de cierre del respaldo precede a sus operaciones.')
        archivo.seek(0)
        return cantidad, catalogo
    except (ijson.JSONError, UnicodeError, RecursionError, TypeError, AttributeError, OverflowError):
        raise ValueError('JSON de respaldo inválido. El caso actual se conserva.') from None


def archivos_iguales(primero, segundo):
    """Comparación exacta con RAM acotada; no cambia los cursores del llamador."""
    try:
        primero.seek(0)
        segundo.seek(0)
        while True:
            bloque = primero.read(BLOQUE)
            if bloque != segundo.read(BLOQUE): return False
            if not bloque: return True
    finally:
        primero.seek(0)
        segundo.seek(0)


def guardar_archivo(archivo):
    from .contexto_bot import bloquear_caso
    from .workspaces import workspace_actual
    cantidad, catalogo = validar_archivo(archivo)
    with transaction.atomic():
        bloquear_caso()
        anterior = RespaldoCaso.objects.filter(workspace_id=workspace_actual()).only('pk').order_by('-created_at', '-pk').first()
        if anterior is not None:
            try:
                # El entrante ya se validó: igualdad exacta implica que la copia
                # previa es válida. No hace falta parsearla otra vez ni escanear
                # todo el historial. Una copia distinta nunca se elimina.
                with archivo_historico(anterior, validar=False) as existente:
                    if archivos_iguales(archivo, existente): return anterior
            except (ValueError, ArithmeticError, TypeError, KeyError, AttributeError):
                pass  # Conservar históricos incompatibles; crear la copia válida.
        archivo.seek(0, 2)
        longitud = archivo.tell()
        archivo.seek(0)
        # Compatibilidad de copias pequeñas; las grandes permanecen en bloques.
        if longitud <= 512 * 1024:
            contenido = json.load(archivo)
            return RespaldoCaso.objects.create(datos=contenido['asientos'], catalogo=catalogo, numero_asientos=cantidad)
        respaldo = RespaldoCaso.objects.create(datos=[], catalogo=catalogo, numero_asientos=cantidad)
        for i in range((longitud + BLOQUE - 1) // BLOQUE):
            RespaldoFragmento.objects.create(respaldo=respaldo, indice=i, contenido=archivo.read(BLOQUE))
        return respaldo


def crear_copia_actual():
    with archivo_actual() as archivo:
        cantidad, catalogo = validar_archivo(archivo)
        if not cantidad and not catalogo: return None
        return guardar_archivo(archivo)


def restaurar_archivo(archivo, session=None):
    from .respaldos import validar_respaldo
    from .contexto_bot import limpiar_tras_guardado
    _, catalogo = validar_archivo(archivo)
    with transaction.atomic():
        from .contexto_bot import bloquear_caso
        bloquear_caso()
        crear_copia_actual()
        AsientoContable.objects.all().delete()
        CuentaContable.objects.all().delete()
        cuentas = {c['codigo']:CuentaContable.objects.create(**c) for c in catalogo}
        for original in items(archivo, 'asientos.item'):
            datos, _ = validar_respaldo({'asientos':[original], 'cuentas':catalogo})
            r = datos[0]
            a = AsientoContable.objects.create(fecha=r['fecha'], descripcion=r['descripcion'], clase=r['clase'],
                flujo_efectivo=r['flujo_efectivo'], fecha_cierre_ejercicio=r['fecha_cierre'],
                fuente_importacion=r['fuente'], observaciones_importacion=r['observaciones'])
            Movimiento.objects.bulk_create([Movimiento(asiento=a, cuenta=cuentas[m['codigo']],
                tipo=m['tipo_movimiento'], monto=m['monto']) for m in r['movimientos']], batch_size=40)
        limpiar_tras_guardado(session)
