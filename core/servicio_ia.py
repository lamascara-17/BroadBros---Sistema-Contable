"""Errores del proveedor sin exponer credenciales ni contenido del ejercicio."""
import json
import logging
import re
from groq import APIConnectionError, APIStatusError, APITimeoutError

logger = logging.getLogger(__name__)


def solicitar_json(client, **parametros):
    try:
        try:
            return client.chat.completions.create(**parametros)
        except APIStatusError as exc:
            cuerpo = exc.body if isinstance(exc.body, dict) else {}
            error = cuerpo.get('error', cuerpo)
            if exc.status_code == 400 and isinstance(error, dict) and error.get('code') == 'json_validate_failed' and 'response_format' in parametros:
                alternativos = dict(parametros)
                alternativos.pop('response_format', None)
                return client.chat.completions.create(**alternativos)
            raise
    except APITimeoutError:
        raise ValueError('Groq tardó demasiado en responder. Intente nuevamente; no se guardó ningún asiento.') from None
    except APIConnectionError:
        raise ValueError('No se pudo conectar con Groq. Intente nuevamente; no se guardó ningún asiento.') from None
    except APIStatusError as exc:
        logger.warning('Fallo de Groq: estado=%s modelo=%s', exc.status_code, parametros.get('model'))
        cuerpo = exc.body if isinstance(exc.body, dict) else {}
        error = cuerpo.get('error', cuerpo)
        detalle = str(error.get('message', '')) if isinstance(error, dict) else ''
        if exc.status_code == 429 and 'request too large' in detalle.lower():
            limite = re.search(r'Limit\s+(\d+)', detalle, re.I)
            solicitado = re.search(r'Requested\s+(\d+)', detalle, re.I)
            cifras = f" Límite: {limite[1]}; solicitud: {solicitado[1]} tokens." if limite and solicitado else ''
            raise ValueError('La solicitud supera el límite de tokens permitido por Groq.' + cifras + ' Esperar no reduce el tamaño de esta solicitud. No se guardó ningún asiento.') from None
        mensajes = {
            401: 'La clave de Groq no es válida. Actualice GROQ_API_KEY en el servicio de Render.',
            403: 'La cuenta de Groq no tiene permiso para utilizar el modelo configurado.',
            404: 'El modelo configurado no está disponible. Revise GROQ_VISION_MODEL y GROQ_TEXT_MODEL en Render.',
            413: 'La solicitud de análisis excede el tamaño o la cantidad de tokens permitidos por Groq.',
            429: 'Groq alcanzó su límite de uso. Espere antes de volver a intentar; si continúa, revise la cuota de la cuenta.',
            400: 'Groq rechazó la solicitud. Revise el modelo configurado y sus límites de imágenes y tokens.',
        }
        mensaje = mensajes.get(exc.status_code, 'Groq no está disponible temporalmente. Intente nuevamente.')
        raise ValueError(mensaje + ' No se guardó ningún asiento.') from None


def leer_json(contenido):
    texto = (contenido or '').strip()
    if texto.startswith('```') and texto.endswith('```'):
        lineas = texto.splitlines()
        if lineas[0].strip() in ('```', '```json'):
            texto = '\n'.join(lineas[1:-1])
    return json.loads(texto, parse_float=str)
