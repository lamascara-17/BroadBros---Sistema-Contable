"""Audio opcional de respuestas con una voz personalizada configurada."""
import os
import re
import httpx
from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST


def configuracion():
    return os.environ.get('ELEVENLABS_API_KEY', ''), os.environ.get('NONOBOT_VOICE_ID', '')


def datos_audio(texto):
    key, voice = configuracion()
    if not key or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', voice):
        return {'audio_personalizado': False}
    return {'audio_personalizado': True,
            'audio_token': signing.dumps({'texto': texto[:6000]}, salt='nonobot-audio', compress=True)}


@require_POST
def respuesta_audio(request):
    token = request.POST.get('token', '')
    if len(token) > 25000:
        return JsonResponse({'error': 'La respuesta de audio es demasiado extensa.'}, status=400)
    try:
        texto = signing.loads(token, salt='nonobot-audio', max_age=3600)['texto']
        if not isinstance(texto, str) or not 1 <= len(texto) <= 6000:
            raise ValueError()
    except (signing.BadSignature, ValueError, TypeError, KeyError):
        return JsonResponse({'error': 'El audio caducó. Vuelve a consultar a ÑoñoBot.'}, status=400)
    key, voice = configuracion()
    if not key or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', voice):
        return JsonResponse({'error': 'La voz personalizada todavía no está configurada.'}, status=503)
    try:
        response = httpx.post(f'https://api.elevenlabs.io/v1/text-to-speech/{voice}',
                              headers={'xi-api-key': key, 'Accept': 'audio/mpeg'},
                              params={'output_format': 'mp3_44100_128'},
                              json={'text': texto, 'model_id': 'eleven_multilingual_v2'}, timeout=35)
        response.raise_for_status()
        if not response.content or not response.headers.get('content-type', '').startswith('audio/'):
            raise ValueError()
        audio = HttpResponse(response.content, content_type='audio/mpeg')
        audio['Cache-Control'] = 'no-store'
        return audio
    except httpx.HTTPStatusError as exc:
        return JsonResponse({'error': 'El servicio de voz alcanzó su cuota. Puedes leer la respuesta.' if exc.response.status_code == 429
                             else 'El servicio de voz personalizada no pudo generar el audio.'}, status=503)
    except Exception:
        return JsonResponse({'error': 'No se pudo generar el audio. Puedes leer la respuesta e intentar nuevamente.'}, status=503)
