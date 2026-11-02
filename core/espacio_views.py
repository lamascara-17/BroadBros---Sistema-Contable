from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import RespaldoCaso


def acceso_libre(request):
    # Compatibilidad con enlaces antiguos: no autentica ni pierde la sesión.
    return redirect('index')


def respaldos(request):
    return render(request, 'respaldos.html', {'respaldos': RespaldoCaso.objects.order_by('-created_at')[:50]})


@require_POST
def restaurar_respaldo(request, pk):
    respaldo = get_object_or_404(RespaldoCaso, pk=pk)
    from .respaldos import restaurar
    from django.contrib import messages
    try:
        restaurar(respaldo)
        messages.success(request, 'Caso restaurado sin renumerar sus cuentas; revise las advertencias de los estados.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('respaldos')


def descargar_respaldo(request, pk):
    import json
    respaldo = get_object_or_404(RespaldoCaso, pk=pk)
    return HttpResponse(json.dumps({'formato':'BROADBROS', 'version':1, 'asientos': respaldo.datos, 'cuentas': respaldo.catalogo}, ensure_ascii=False), content_type='application/json',
                        headers={'Content-Disposition': f'attachment; filename="BROADBROS_respaldo_{pk}.json"'})


def estado_patrimonio(request):
    from .reporte_utils import contexto_estados
    return render(request, 'estado_patrimonio.html', contexto_estados())


def estado_flujos(request):
    from .reporte_utils import contexto_estados
    return render(request, 'estado_flujos.html', contexto_estados())



def descargar_actual(request):
    import json
    from .respaldos import serializar_caso
    return HttpResponse(json.dumps(serializar_caso(), ensure_ascii=False), content_type='application/json',
                        headers={'Content-Disposition':'attachment; filename=BROADBROS_caso_actual.json'})


@require_POST
def importar_respaldo(request):
    import json
    from django.contrib import messages
    from django.db import transaction
    from .respaldos import validar_respaldo, restaurar
    archivo = request.FILES.get('respaldo')
    try:
        if not archivo or not archivo.name.lower().endswith('.json') or archivo.size > 2*1024*1024:
            raise ValueError('Selecciona un respaldo JSON de hasta 2 MB.')
        def rechazar_constante(valor):
            raise ValueError('El respaldo contiene un número no finito.')
        try:
            contenido = json.loads(archivo.read().decode('utf-8-sig'), parse_float=str, parse_constant=rechazar_constante)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            raise ValueError('No se pudo leer el JSON del respaldo. El caso actual se conserva.') from None
        datos,catalogo = validar_respaldo(contenido)
        with transaction.atomic():
            respaldo=RespaldoCaso.objects.create(datos=datos,catalogo=catalogo)
            restaurar(respaldo)
        request.session.pop('nonobot_turnos',None)
        messages.success(request,'Respaldo importado en esta sesión. El caso anterior se conserva en Casos anteriores.')
    except (ValueError, ArithmeticError) as exc:
        messages.error(request,str(exc))
    return redirect('respaldos')
