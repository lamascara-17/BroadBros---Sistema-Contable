"""Observaciones de lectura sin bucles de texto ni duplicados visuales."""
import re
import unicodedata


def partes_notas(valores):
    if not isinstance(valores, list) or len(valores) > 100 or any(not isinstance(v, str) for v in valores):
        raise ValueError('Las notas de revisión no son válidas.')
    partes = []
    for valor in valores:
        if len(valor) > 10000:
            raise ValueError('La respuesta contiene una observación demasiado extensa; reintente el análisis.')
        for parte in re.split(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿])|\n+', valor):
            parte = re.sub(r'\s+', ' ', parte).strip()
            if parte: partes.append(parte)
    return partes


def normalizar_notas(valores):
    salida, vistas = [], set()
    for parte in partes_notas(valores):
        key = ''.join(c for c in unicodedata.normalize('NFKD', parte.casefold()) if not unicodedata.combining(c))
        key = re.sub(r'[^\w]+', ' ', key).strip()
        if key not in vistas:
            vistas.add(key)
            salida.append(parte)
    return salida


def notas_repetitivas(datos):
    for key in ('pendientes', 'supuestos'):
        partes = partes_notas(datos.get(key, []))
        unicas = normalizar_notas(datos.get(key, []))
        # Una repetición aislada no invalida un caso; un bucle como el de la
        # captura requiere otro análisis y nunca se acepta silenciosamente.
        if len(partes) >= 5 and len(partes) - len(unicas) >= 3 and len(unicas) < len(partes)*.7:
            return True
    return False
