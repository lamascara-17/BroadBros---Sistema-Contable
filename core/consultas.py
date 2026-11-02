"""Detalle contable en una consulta, sin miles de OR para precargar cuentas."""
from django.db.models import Prefetch
from .models import Movimiento
from .workspaces import workspace_actual


def movimientos_con_cuentas():
    detalles = Movimiento.objects.select_related('cuenta').order_by('pk')
    if workspace_actual() is not None:
        detalles = detalles.filter(cuenta__workspace_id=workspace_actual())
    return Prefetch('movimientos', queryset=detalles)
