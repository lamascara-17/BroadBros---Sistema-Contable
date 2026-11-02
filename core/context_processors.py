from django.conf import settings


def almacenamiento(request):
    return {'almacenamiento_temporal': settings.RENDER_EPHEMERAL_SQLITE}
