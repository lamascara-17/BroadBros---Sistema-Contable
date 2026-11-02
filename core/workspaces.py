"""Consultas cerradas sin ámbito; acceso global administrativo solo explícito."""
from contextlib import contextmanager
from contextvars import ContextVar
from django.db import models

actual = ContextVar('broadbros_workspace', default=None)
administrativo = ContextVar('broadbros_administrativo', default=False)


def workspace_actual():
    return actual.get()


@contextmanager
def acceso_administrativo():
    """Solo comandos, migraciones operativas, Django Admin y fixtures aisladas."""
    token = administrativo.set(True)
    try:
        yield
    finally:
        administrativo.reset(token)


class ScopedQuerySet(models.QuerySet):
    def _exigir_ambito(self):
        if workspace_actual() is None and not administrativo.get():
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('La escritura requiere un espacio de trabajo o acceso administrativo explícito.')

    def create(self, **kwargs):
        self._exigir_ambito()
        return super().create(**kwargs)

    def bulk_create(self, objs, **kwargs):
        self._exigir_ambito()
        return super().bulk_create(objs, **kwargs)


class WorkspaceManager(models.Manager.from_queryset(ScopedQuerySet)):
    def get_queryset(self):
        qs = super().get_queryset()
        workspace = workspace_actual()
        if workspace is not None:
            return qs.filter(workspace_id=workspace)
        return qs if administrativo.get() else qs.none()


class MovimientoManager(models.Manager.from_queryset(ScopedQuerySet)):
    def get_queryset(self):
        qs = super().get_queryset()
        workspace = workspace_actual()
        if workspace is not None:
            return qs.filter(asiento__workspace_id=workspace)
        return qs if administrativo.get() else qs.none()
