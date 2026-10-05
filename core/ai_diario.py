import json
import os
from PIL import Image
from google import genai
from django.conf import settings

def interpretar_caso_imagen(imagen_file, api_key: str = None):
    """
    Recibe la imagen del examen/caso contable y extrae los asientos
    para el Libro Diario en formato JSON cuadrado bajo el PCGE.
    """
    key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
    if not key:
        raise ValueError("Se requiere una API Key válida de Gemini.")

    client = genai.Client(api_key=key)
    img = Image.open(imagen_file)

    prompt = """
    Eres un profesor y auditor contable experto en el Plan Contable General Empresarial (PCGE) del Perú.
    Analiza la imagen que contiene las transacciones u operaciones del caso contable.
    
    Tu objetivo es armar el LIBRO DIARIO estricto.
    Debes devolver ÚNICAMENTE un arreglo JSON válido con el siguiente formato exacto:

    [
      {
        "fecha": "YYYY-MM-DD",
        "descripcion": "Asiento 1: Aporte de capital",
        "glosa": "Por el aporte inicial de capital en efectivo",
        "movimientos": [
          {
            "codigo": "10",
            "nombre": "Caja y Bancos",
            "tipo_cuenta": "activo",
            "tipo_movimiento": "debe",
            "monto": 10000.00
          },
          {
            "codigo": "50",
            "nombre": "Capital Social",
            "tipo_cuenta": "patrimonio",
            "tipo_movimiento": "haber",
            "monto": 10000.00
          }
        ]
      }
    ]

    Reglas obligatorias:
    1. 'tipo_cuenta' debe ser exactamente uno de: 'activo', 'pasivo', 'patrimonio', 'ingreso', 'gasto'.
    2. 'tipo_movimiento' debe ser: 'debe' o 'haber'.
    3. Partida doble estricta: Suma Debe == Suma Haber en CADA asiento.
    4. Responde ÚNICAMENTE el bloque JSON crudo (sin ```json ni ``` ni texto explicativo).
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[img, prompt]
    )

    txt = response.text.strip()
    if txt.startswith("```json"):
        txt = txt[7:]
    if txt.startswith("```"):
        txt = txt[3:]
    if txt.endswith("```"):
        txt = txt[:-3]

    return json.loads(txt.strip())