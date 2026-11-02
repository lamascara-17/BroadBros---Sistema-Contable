from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from .workspaces import actual


class WorkspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.WORKSPACE_ISOLATION or request.path.startswith(('/admin/', '/static/')):
            return self.get_response(request)
        from .models import Workspace
        key = request.session.get('workspace_id')
        workspace = Workspace.objects.filter(pk=key).first() if key else None
        if request.user.is_authenticated:
            if workspace and workspace.owner_id is None:
                workspace.owner = request.user
                workspace.save(update_fields=['owner'])
            elif not workspace or workspace.owner_id != request.user.pk:
                workspace = Workspace.objects.filter(owner=request.user).order_by('created_at').first()
                if workspace is None:
                    workspace = Workspace.objects.create(owner=request.user)
        elif workspace and workspace.owner_id is not None:
            workspace = None
        if workspace is None:
            workspace = Workspace.objects.create()
        request.workspace = workspace
        request.session['workspace_id'] = str(workspace.pk)
        token = actual.set(workspace.pk)
        try:
            if settings.AI_REQUIRE_LOGIN and not request.user.is_authenticated and request.method == 'POST' and request.path in ('/chatbot/', '/chatbot/voz/', '/chatbot/audio/', '/cargar-texto/', '/cargar-imagen/'):
                return JsonResponse({'error': 'Ingresa a tu cuenta para procesar casos o utilizar la IA.'}, status=401)
            if request.method == 'POST' and request.path in ('/chatbot/', '/chatbot/voz/', '/chatbot/audio/', '/cargar-texto/', '/cargar-imagen/'):
                from time import time
                limit = 12 if request.path == '/chatbot/' else 6
                bucket = f'quota:{workspace.pk}:{request.path}:{int(time())//60}'
                if cache.add(bucket, 1, 65):
                    count = 1
                else:
                    count = cache.incr(bucket)
                if count > limit:
                    response = JsonResponse({'error': 'Demasiados intentos. Espera un minuto antes de volver a intentar.'}, status=429)
                    response['Retry-After'] = '60'
                    return response
            return self.get_response(request)
        finally:
            actual.reset(token)
