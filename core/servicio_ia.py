"""Errores del proveedor sin exponer credenciales ni contenido del ejercicio."""
import json
import logging
import re
from groq import APIConnectionError, APIStatusError, APITimeoutError

logger = logging.getLogger(__name__)


class LimiteSalidaTokens(ValueError):
    def __init__(self, limite):
        self.limite = limite
        super().__init__(f'La solicitud supera el límite de salida de Groq ({limite} tokens). No se guardó ningún asiento.')


def solicitar_json(client, **parametros):
    try:
        try:
            return client.chat.completions.create(**parametros)
        except APIStatusError as exc:
            cuerpo = exc.body if isinstance(exc.body, dict) else {}
            error = cuerpo.get('error', cuerpo)
            if exc.status_code == 400 and isinstance(error, dict) and error.get('code') == 'json_validate_failed':
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
        cuerpo=exc.body if isinstance(exc.body,dict) else {}
        error=cuerpo.get('error',cuerpo)
        texto=str(error.get('message','')) if isinstance(error,dict) else ''
        limite=re.search(r'\bLimit\s*[:=]?\s*([\d,]+)',texto,re.I)
        if exc.status_code in (400,429) and 'request too large' in texto.lower() and ('OTPM' in texto.upper() or 'output tokens per minute' in texto.lower()) and limite:
            cantidad=int(limite.group(1).replace(',',''))
            if cantidad>0:raise LimiteSalidaTokens(cantidad) from None
        mensajes = {
            401: 'La clave de Groq no es válida. Actualice GROQ_API_KEY en el servicio de Render.',
            403: 'La cuenta de Groq no tiene permiso para utilizar el modelo configurado.',
            404: 'El modelo configurado no está disponible. Revise GROQ_VISION_MODEL y GROQ_TEXT_MODEL en Render.',
            413: 'La imagen excede el tamaño permitido por Groq. Reduzca su tamaño.',
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
