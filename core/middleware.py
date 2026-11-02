from uuid import UUID
from time import time
from hashlib import sha256
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from .workspaces import actual, acceso_administrativo

AI_PATHS = {'/chatbot/': 12, '/chatbot/voz/': 6, '/chatbot/audio/': 6,
            '/cargar-texto/': 6, '/cargar-imagen/': 6, '/cargar-imagen/revisar/': 6}


def excede_cuota(clave, limite):
    if cache.add(clave, 1, 65):
        return False
    try:
        return cache.incr(clave) > limite
    except ValueError:  # La clave pudo vencer entre add e incr.
        return not cache.add(clave, 1, 65)


class WorkspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/'):
            espacio_previo = request.session.get('workspace_id')
            if request.user.is_active and request.user.is_staff:
                with acceso_administrativo():
                    response = self.get_response(request)
            else:
                response = self.get_response(request)
            # Django Admin puede rotar o vaciar la sesión al salir. Su acceso
            # administrativo no debe hacer perder el espacio público previo.
            if espacio_previo and not request.session.get('workspace_id'):
                request.session['workspace_id'] = espacio_previo
            return response
        if not settings.WORKSPACE_ISOLATION or request.path.startswith('/static/'):
            return self.get_response(request)
        from .models import Workspace
        key = request.session.get('workspace_id')
        try:
            workspace = Workspace.objects.filter(pk=UUID(str(key))).first() if key else None
        except (ValueError, TypeError, AttributeError):
            workspace = None
        # La cookie de sesión es la única asociación pública. No se adopta,
        # intercambia ni reasigna un espacio al iniciar sesión en Django Admin.
        if workspace is None:
            workspace = Workspace.objects.create()
        request.workspace = workspace
        request.session['workspace_id'] = str(workspace.pk)
        token = actual.set(workspace.pk)
        try:
            if request.method == 'POST' and request.path in AI_PATHS:
                minuto = int(time()) // 60
                # REMOTE_ADDR no confía en cabeceras X-Forwarded-For del visitante.
                ip = sha256(request.META.get('REMOTE_ADDR', '').encode()).hexdigest()
                saturada = excede_cuota(f'quota-ip:{ip}:{minuto}', 120)
                saturada = excede_cuota(f'quota:{workspace.pk}:{request.path}:{minuto}', AI_PATHS[request.path]) or saturada
                if saturada:
                    if request.path.startswith('/chatbot/') or 'application/json' in request.headers.get('Accept', ''):
                        response = JsonResponse({'error': 'Demasiados intentos. Espera un minuto antes de volver a intentar.'}, status=429)
                    else:
                        response = render(request, 'limite_solicitudes.html', status=429)
                    response['Retry-After'] = '60'
                    return response
            return self.get_response(request)
        finally:
            actual.reset(token)
