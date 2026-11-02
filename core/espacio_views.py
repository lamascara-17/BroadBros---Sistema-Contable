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
    from .respaldo_stream import archivo_historico
    return respuesta_archivo(request, lambda: archivo_historico(respaldo), f'BROADBROS_respaldo_{pk}.json')


def estado_patrimonio(request):
    from .reporte_utils import contexto_estados
    return render(request, 'estado_patrimonio.html', contexto_estados())


def estado_flujos(request):
    from .reporte_utils import contexto_estados
    return render(request, 'estado_flujos.html', contexto_estados())



def respuesta_archivo(request, preparar, nombre):
    from django.http import FileResponse
    from django.contrib import messages
    try:
        archivo = preparar()
    except (ValueError, ArithmeticError) as exc:
        messages.error(request, f'No se generó un archivo incompleto o incompatible: {exc} Los datos originales se conservan. Contacta al administrador para una copia completa de la base antes de cualquier cambio.')
        return redirect('respaldos')
    archivo.seek(0, 2)
    longitud = archivo.tell()
    archivo.seek(0)
    if longitud <= 512 * 1024:
        try: respuesta = HttpResponse(archivo.read(), content_type='application/json')
        finally: archivo.close()
        respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    else:
        respuesta = FileResponse(archivo, as_attachment=True, filename=nombre, content_type='application/json')
    respuesta['Cache-Control'] = 'no-store'
    return respuesta


def descargar_actual(request):
    from .respaldo_stream import archivo_actual
    return respuesta_archivo(request, archivo_actual, 'BROADBROS_caso_actual.json')


@require_POST
def importar_respaldo(request):
    from tempfile import TemporaryFile
    from django.contrib import messages
    from django.db import transaction
    from .respaldos import MAX_RESPALDO_BYTES
    from .respaldo_stream import validar_archivo, guardar_archivo, restaurar_archivo
    archivo = request.FILES.get('respaldo')
    try:
        if not archivo or not archivo.name.lower().endswith('.json') or archivo.size > MAX_RESPALDO_BYTES:
            raise ValueError('Selecciona un respaldo JSON de hasta 256 MiB.')
        with TemporaryFile(mode='w+b') as temporal:
            total = 0
            for i, bloque in enumerate(archivo.chunks(chunk_size=64 * 1024)):
                total += len(bloque)
                if total > MAX_RESPALDO_BYTES: raise ValueError('El respaldo supera los 256 MiB.')
                if i == 0 and bloque.startswith(b'\xef\xbb\xbf'): bloque = bloque[3:]
                temporal.write(bloque)
            validar_archivo(temporal)
            with transaction.atomic():
                restaurar_archivo(temporal, session=request.session)
                guardar_archivo(temporal)
        messages.success(request,'Respaldo importado en esta sesión. El caso anterior se conserva en Casos anteriores.')
    except (ValueError, ArithmeticError) as exc:
        messages.error(request,str(exc))
    return redirect('respaldos')
