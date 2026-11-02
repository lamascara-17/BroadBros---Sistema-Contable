from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import RespaldoCaso


def acceso_libre(request):
    # Compatibilidad con enlaces antiguos: no autentica ni pierde la sesión.
    return redirect('index')


def respaldos(request):
    from django.core.paginator import Paginator
    from urllib.parse import urlencode
    from .forms import BuscarRespaldosForm

    formulario = BuscarRespaldosForm(request.GET)
    casos = RespaldoCaso.objects.order_by('-created_at', '-pk')
    filtros = {}
    if formulario.is_valid():
        for campo, lookup in (('desde', 'created_at__date__gte'), ('hasta', 'created_at__date__lte')):
            fecha = formulario.cleaned_data[campo]
            if fecha:
                casos = casos.filter(**{lookup: fecha})
                filtros[campo] = fecha.isoformat()
    else:
        casos = casos.none()
    pagina = Paginator(casos, 20).get_page(request.GET.get('pagina'))
    return render(request, 'respaldos.html', {
        'respaldos': pagina.object_list, 'pagina': pagina,
        'formulario_busqueda': formulario, 'filtros_url': urlencode(filtros),
    })


@require_POST
def restaurar_respaldo(request, pk):
    respaldo = get_object_or_404(RespaldoCaso, pk=pk)
    from .respaldos import restaurar
    from django.contrib import messages
    try:
        restaurar(respaldo, session=request.session)
        messages.success(request, 'Caso restaurado sin renumerar sus cuentas; revise las advertencias de los estados.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('respaldos')


def descargar_respaldo(request, pk):
    respaldo = get_object_or_404(RespaldoCaso, pk=pk)
    return respuesta_respaldo(request, {'formato':'BROADBROS', 'version':1,
        'asientos': respaldo.datos, 'cuentas': respaldo.catalogo}, f'BROADBROS_respaldo_{pk}.json')


def estado_patrimonio(request):
    from .reporte_utils import contexto_estados
    return render(request, 'estado_patrimonio.html', contexto_estados())


def estado_flujos(request):
    from .reporte_utils import contexto_estados
    return render(request, 'estado_flujos.html', contexto_estados())



def respuesta_respaldo(request, contenido, nombre):
    from .respaldos import codificar_respaldo
    from django.contrib import messages
    try:
        archivo = codificar_respaldo(contenido)
    except (ValueError, ArithmeticError) as exc:
        messages.error(request, f'No se generó un archivo incompleto: {exc} Los datos originales se conservan.')
        return redirect('respaldos')
    return HttpResponse(archivo, content_type='application/json', headers={
        'Content-Disposition': f'attachment; filename="{nombre}"', 'Cache-Control':'no-store'})


def descargar_actual(request):
    from .respaldos import serializar_caso
    return respuesta_respaldo(request, serializar_caso(), 'BROADBROS_caso_actual.json')


@require_POST
def importar_respaldo(request):
    import json
    from django.contrib import messages
    from django.db import transaction
    from .respaldos import validar_respaldo, restaurar, MAX_RESPALDO_BYTES
    archivo = request.FILES.get('respaldo')
    try:
        if not archivo or not archivo.name.lower().endswith('.json') or archivo.size > MAX_RESPALDO_BYTES:
            raise ValueError('Selecciona un respaldo JSON de hasta 256 MB.')
        def rechazar_constante(valor):
            raise ValueError('El respaldo contiene un número no finito.')
        try:
            bruto = archivo.read(MAX_RESPALDO_BYTES + 1)
            if len(bruto) > MAX_RESPALDO_BYTES:
                raise ValueError('El respaldo supera los 256 MB.')
            contenido = json.loads(bruto.decode('utf-8-sig'), parse_float=str, parse_constant=rechazar_constante)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            raise ValueError('No se pudo leer el JSON del respaldo. El caso actual se conserva.') from None
        datos,catalogo = validar_respaldo(contenido)
        with transaction.atomic():
            respaldo=RespaldoCaso.objects.create(datos=datos,catalogo=catalogo)
            restaurar(respaldo, session=request.session)
        messages.success(request,'Respaldo importado en esta sesión. El caso anterior se conserva en Casos anteriores.')
    except (ValueError, ArithmeticError) as exc:
        messages.error(request,str(exc))
    return redirect('respaldos')
