"""Transcripción de consultas de voz sin depender del dictado del navegador."""
from pathlib import Path
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from groq import Groq, APIConnectionError, APIStatusError, APITimeoutError


@require_POST
def transcribir_voz(request):
    audio = request.FILES.get('audio')
    formatos = {'.webm', '.mp4', '.m4a', '.ogg', '.wav'}
    if not audio or not audio.size or audio.size > 10 * 1024 * 1024:
        return JsonResponse({'error': 'Graba una consulta de hasta un minuto y 10 MB.'}, status=400)
    extension = Path(audio.name).suffix.lower()
    if extension not in formatos:
        return JsonResponse({'error': 'El formato de audio no es compatible.'}, status=400)
    key = getattr(settings, 'GROQ_API_KEY', '')
    if not key:
        return JsonResponse({'error': 'La transcripción de voz no está configurada en el servidor.'}, status=503)
    try:
        client = Groq(api_key=key, timeout=30, max_retries=0)
        resultado = client.audio.transcriptions.create(
            file=('consulta' + extension, audio.read()), model='whisper-large-v3-turbo',
            language='es', response_format='json', temperature=0)
        texto = (resultado.text or '').strip()
        if not texto:
            return JsonResponse({'error': 'No se detectó voz. Intenta hablar más cerca del micrófono.'}, status=422)
        return JsonResponse({'texto': texto[:20000]})
    except APITimeoutError:
        return JsonResponse({'error': 'La transcripción tardó demasiado. Vuelve a intentar.'}, status=504)
    except APIConnectionError:
        return JsonResponse({'error': 'El servidor no pudo conectar con la transcripción. Intenta nuevamente.'}, status=503)
    except APIStatusError as exc:
        mensajes = {429: 'Groq alcanzó su límite de audio. Espera antes de reintentar.',
                    401: 'La clave de Groq del servidor no es válida.',
                    403: 'Groq no permite la transcripción con esta cuenta.',
                    400: 'No se pudo leer la grabación. Intenta grabarla nuevamente.',
                    413: 'La grabación es demasiado grande. Haz una consulta más breve.'}
        return JsonResponse({'error': mensajes.get(exc.status_code, 'La transcripción no está disponible temporalmente.')},
                            status=429 if exc.status_code == 429 else 503)
    except Exception:
        return JsonResponse({'error': 'No se pudo transcribir la consulta. Intenta nuevamente.'}, status=503)
