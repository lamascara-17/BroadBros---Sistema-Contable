from .models import CuentaContable, AsientoContable, Movimiento, RespaldoCaso
from django.db import transaction


def crear_respaldo():
    anteriores = list(AsientoContable.objects.prefetch_related('movimientos__cuenta'))
    catalogo = list(CuentaContable.objects.values('codigo', 'nombre', 'tipo', 'subcategoria'))
    if not anteriores and not catalogo: return None
    datos = [{'fecha': str(a.fecha), 'descripcion': a.descripcion, 'clase': a.clase,
              'flujo_efectivo': a.flujo_efectivo, 'fecha_cierre': str(a.fecha_cierre_ejercicio) if a.fecha_cierre_ejercicio else None,
              'fuente': a.fuente_importacion, 'observaciones': a.observaciones_importacion,
              'movimientos': [{'codigo': m.cuenta.codigo, 'nombre': m.cuenta.nombre, 'tipo_cuenta': m.cuenta.tipo,
                  'subcategoria': m.cuenta.subcategoria, 'tipo_movimiento': m.tipo, 'monto': str(m.monto)} for m in a.movimientos.all()]} for a in anteriores]
    return RespaldoCaso.objects.create(datos=datos, catalogo=catalogo)


def restaurar(respaldo):
    from .importacion_general import validar_asientos
    # Se validan estructura y partida doble, sin renumerar el catálogo histórico.
    if respaldo.datos: validar_asientos(respaldo.datos)
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
