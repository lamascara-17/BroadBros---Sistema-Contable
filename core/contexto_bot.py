"""La conversación pertenece a un caso y solo se invalida después del commit."""
from django.db import transaction
from django.db.models import Count, Max
from .models import AsientoContable
from .workspaces import workspace_actual


def limpiar_tras_guardado(session):
    if session is None:
        return
    def limpiar():
        session.pop('nonobot_turnos', None)
        session.pop('nonobot_caso', None)
    transaction.on_commit(limpiar)


def firma_caso():
    # Reemplazar/restaurar recrea las cabeceras con IDs nuevos. Esta marca evita
    # reutilizar una respuesta antigua incluso si otra petición grabó su sesión
    # después del commit o un comando administrativo cambió el ejercicio.
    datos = AsientoContable.objects.aggregate(total=Count('pk'), ultimo=Max('pk'))
    return {'workspace': str(workspace_actual()), **datos}
