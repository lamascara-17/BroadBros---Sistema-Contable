"""Ámbito por sesión o cuenta; nunca se comparte el caso con otros visitantes."""
from contextvars import ContextVar
from django.db import models

actual = ContextVar('broadbros_workspace', default=None)


def workspace_actual():
    return actual.get()


class WorkspaceManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        workspace = workspace_actual()
        return qs.filter(workspace_id=workspace) if workspace is not None else qs


class MovimientoManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        workspace = workspace_actual()
        return qs.filter(asiento__workspace_id=workspace) if workspace is not None else qs
