"""La conversación pertenece a un caso y solo se invalida después del commit."""
from django.db import transaction
from django.db.models import Count, Max
from .models import AsientoContable, Workspace
from .workspaces import workspace_actual


def limpiar_tras_guardado(session):
    if session is None:
        return
    def limpiar():
        session.pop('nonobot_turnos', None)
        session.pop('nonobot_caso', None)
    transaction.on_commit(limpiar)


def firma_caso():
    workspace = workspace_actual()
    if workspace is not None:
        revision = Workspace.objects.values_list('revision_contable', flat=True).get(pk=workspace)
        return {'workspace': str(workspace), 'revision': revision}
    # Herramientas administrativas y fixtures históricas sin visitante.
    datos = AsientoContable.objects.aggregate(total=Count('pk'), ultimo=Max('pk'))
    return {'workspace': str(workspace), **datos}


def conversacion_caso(session, firma):
    """Estado compartido entre workers; la sesión no puede resucitar turnos viejos."""
    workspace = workspace_actual()
    if workspace is None:
        return (session.get('nonobot_turnos', [])[-4:] if session.get('nonobot_caso') == firma else []), None
    estado = Workspace.objects.get(pk=workspace)
    turnos = estado.bot_turnos[-4:] if estado.bot_revision == firma['revision'] else []
    return turnos, estado.bot_sequence


def guardar_conversacion(firma, secuencia, turnos):
    """Compare-and-swap: una respuesta tardía nunca pisa otra ni un caso nuevo."""
    if workspace_actual() is None:
        return firma_caso() == firma
    from django.db.models import F
    if firma.get('workspace') != str(workspace_actual()):
        return False
    return bool(Workspace.objects.filter(pk=workspace_actual(),
        revision_contable=firma['revision'], bot_sequence=secuencia).update(
            bot_sequence=F('bot_sequence') + 1, bot_revision=firma['revision'], bot_turnos=turnos))


def bloquear_caso():
    """Serializa escrituras por visitante sin incrementar la revisión por sí sola."""
    from django.db.models import F
    if workspace_actual() is not None:
        Workspace.objects.filter(pk=workspace_actual()).update(revision_contable=F('revision_contable'))
