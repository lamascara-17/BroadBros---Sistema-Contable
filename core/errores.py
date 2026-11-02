from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect
import logging


def exportacion_segura(vista):
    @wraps(vista)
    def ejecutar(request, *args, **kwargs):
        try:
            return vista(request, *args, **kwargs)
        except Exception:
            logging.getLogger(__name__).error('Fallo del generador de reportes; no se modificaron los asientos.')
            messages.error(request, 'No se pudo generar el archivo. Los datos se conservan; vuelva a intentar o elija otro formato.')
            return redirect('reporte_completo')
    return ejecutar
