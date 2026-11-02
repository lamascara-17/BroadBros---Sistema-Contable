from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import RespaldoCaso, CuentaContable


def registrar_usuario(request):
    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.save())
        return redirect('index')
    return render(request, 'registro.html', {'form': form})


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
    return HttpResponse(json.dumps({'asientos': respaldo.datos, 'cuentas': respaldo.catalogo}, ensure_ascii=False), content_type='application/json',
                        headers={'Content-Disposition': f'attachment; filename="BROADBROS_respaldo_{pk}.json"'})


def estado_patrimonio(request):
    from .reporte_utils import contexto_estados
    return render(request, 'estado_patrimonio.html', contexto_estados())


def estado_flujos(request):
    from .reporte_utils import contexto_estados
    return render(request, 'estado_flujos.html', contexto_estados())
