"""Lectura de imágenes separada de las reglas y de la persistencia contable."""
import base64
from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError
from groq import Groq
from django.conf import settings
from .ciclo_contable import generar_asientos
from .servicio_ia import solicitar_json, leer_json

PROMPT_LECTURA = """
Transcribe todas las operaciones del ejercicio de la imagen completa.
No generes asientos, cuentas, costo de ventas ni depreciación. Solo extrae datos.
Si una frase contiene dos compras distintas, sepáralas en dos operaciones.
No incorpores el texto de pie, título o consignas como una operación.
Respeta el año del ejercicio (09 significa 2009), no el año actual.
No agregues IGV, impuestos, pagos, costos o saldos que no aparezcan.
Usa números JSON sin separadores de miles. Cualquier dato ilegible es null
acompañado de una explicación en errores_lectura; nunca una conjetura.

Devuelve únicamente este objeto JSON:
{
 "empresa_nueva": true o false según el texto,
 "metodo_inventario": "periodico" si hay inventario físico final,
 "inventario_inicial": importe leído, o null si no se indica,
 "saldos_apertura": [{"concepto":"caja|banco|clientes|proveedores|capital|mercaderias", "monto": importe}] o [],
 "fecha_apertura": fecha indicada, o null,
 "fecha_cierre": "YYYY-MM-DD",
 "errores_lectura": [],
 "observaciones": [],
 "texto_leido": "transcripción literal completa del ejercicio, incluso operaciones de otros tipos",
 "operaciones": [{"fecha":"YYYY-MM-DD","tipo":"...","texto":"frase literal leída","monto": importe o null, ...}]
}

Tipos y campos:
- aporte_efectivo: monto.
- compra_mercaderia: monto, pago = contado, credito o letras; null si no se indica.
- compra_activo: monto, pago (null si no se indica); vida_util_anios, residual_porcentaje y
  fecha_inicio_uso SOLO si el texto los indica. Si no indica vida útil omite esos campos.
- venta: monto total, porcentaje_contado (100 si dice contado, 0 si crédito;
  usa el porcentaje explícito en ventas mixtas), descuento_porcentaje,
  descuento_dias, plazo_dias si aparecen condiciones de factura.
  "10/20 n/30" significa 10% de descuento dentro de 20 días; plazo 30 días.
- cobro_factura: fecha_factura indicada en el texto, monto nominal solo si
  está escrito; si dice cobra la factura sin importe, monto = null. NO calcules cobro neto.
- devolucion_proveedor: monto, pago = reembolso si devuelve efectivo,
  credito si reduce deuda.
- donacion_mercaderia: monto de la donación recibida.
- perdida_mercaderia: monto de pérdida por siniestro.
- sueldos_pendientes: monto pendiente de pago.
- pago_servicios: monto total SOLO si escrito; si no, null.
  detalles = [{"concepto":"alquiler, luz, agua u otro texto", "monto":importe escrito}].
- inventario_final: monto del inventario físico (puede ser cero), fecha de cierre.
- pago_proveedor_inicial: porcentaje de la deuda a proveedores del inventario
  inicial que se cancela; monto = null si solo aparece un porcentaje.
- cobro_letras / pago_letras: contraparte literal, letras_numeros si se identifican,
  o cantidad_letras si solo dice cuántas; monto = null si no está escrito.
  fecha_documento SOLO si aparece una referencia explícita a la emisión.
- no_soportada: cualquier operación diferente; conserva su texto y datos literales.
  No la omitas ni la marques como ilegible por no pertenecer a los tipos anteriores.
  Se analizará en la revisión general. Una fecha o importe realmente ausente
  puede ser null; especifica el dato faltante en errores_lectura y conserva el resto.

En casos con apertura, el párrafo "presenta el siguiente inventario" es el
estado inicial, no un inventario físico de mercadería ni un aporte nuevo.
Extrae cada saldo: efectivo => caja, cuenta corriente => banco, Clientes =>
clientes, Proveedores => proveedores y capital => capital. No lo omitas.
Si no hay inventario físico final, metodo_inventario = "sin_cierre" y NO crees
inventario_final. fecha_cierre es el último día de operaciones si no hay otro corte.
No calcules saldos, impuestos ni importes de letras. 2.500.000 significa 2500000.

Campos adicionales de compra, venta y pago_servicios en casos con apertura:
- impuesto = incluido si dice IVA/IGV incluido, neto si dice importe neto,
  no_indicado si no habla de impuesto. tasa_impuesto = porcentaje SOLO si escrito.
  La falta de una tasa explícita NO es un error de lectura: se configura fuera de la imagen.
- medio_pago = efectivo, cheque o banco; omite si no hay pago/cobro al contado.
- contraparte = nombre literal del cliente/proveedor para vincular las letras.
- numero_letras = cantidad emitida, letras_numeros = lista de identificadores
  si aparece (101 - 102 - 103 y 104 => ["101","102","103","104"]), o null.
  letras_importes SOLO si se escriben importes individuales; no los calcules.
- venta: saldo_documentado = true si el saldo se recibe con letras, false si
  se indica crédito sin letras. porcentaje_contado es el porcentaje recibido.
Los cobros y pagos con cheque van al banco, nunca a caja. El pago de "50% de la
deuda del inventario a proveedores" referencia el saldo de apertura, no la
compra posterior con letras. Transcribe el arriendo como pago_servicios.

errores_lectura contiene SOLO datos ilegibles, contradictorios o imposibles de determinar.
observaciones contiene notas informativas; separar compras o dejar el nominal de
una factura sin monto escrito son notas normales, no errores de lectura.

Incluye todas las fechas, importes y porcentajes de las dos partes de la imagen.
El inventario final es un dato para el ajuste, no una compra. El valor residual
NO es una depreciación. Verifica la lista de operaciones contra la imagen antes
 de responder. No omitas la donación, devoluciones, pérdidas, cobros ni datos del activo.
"""


def preparar_imagenes(imagen_file):
    """Corrige orientación y conserva una vista completa de alta resolución."""
    try:
        with Image.open(imagen_file) as original:
            if original.format not in ('JPEG', 'PNG', 'WEBP') or getattr(original, 'n_frames', 1) != 1:
                raise ValueError('Use una imagen estática JPG, PNG o WEBP.')
            if original.width * original.height > 20_000_000:
                raise ValueError('La imagen tiene demasiados píxeles. Reduzca su tamaño.')
            img = ImageOps.exif_transpose(original)
            if img.mode in ('RGBA', 'LA') or 'transparency' in img.info:
                rgba = img.convert('RGBA')
                img = Image.new('RGB', rgba.size, 'white')
                img.paste(rgba, mask=rgba.getchannel('A'))
            else:
                img = img.convert('RGB')
            w, h = img.size
            if min(w, h) < 150:
                raise ValueError('La imagen es demasiado pequeña para leer el caso.')
            # Cada vista consume 2048 tokens; evitamos triplicar la misma imagen.
            regiones = [img]
            contenido = []
            for region in regiones:
                ancho = min(1800, max(1200, region.width))
                alto = round(region.height * ancho / region.width)
                region = region.resize((ancho, alto), Image.Resampling.LANCZOS)
                region.thumbnail((2400, 2400))
                stream = BytesIO()
                region.save(stream, format='JPEG', quality=92)
                b64 = base64.b64encode(stream.getvalue()).decode('ascii')
                contenido.append({'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}})
            return contenido
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError('No se pudo leer el archivo como una imagen válida.') from None


def extraer_operaciones(imagen_file, api_key=None):
    key = api_key or getattr(settings, 'GROQ_API_KEY', '')
    if not key:
        raise ValueError('Configure GROQ_API_KEY para utilizar la lectura de imágenes.')
    contenido = [{'type': 'text', 'text': PROMPT_LECTURA}] + preparar_imagenes(imagen_file)
    client = Groq(api_key=key, timeout=90, max_retries=1)
    respuesta = solicitar_json(client,
        model=getattr(settings, 'GROQ_VISION_MODEL', 'qwen/qwen3.8-27b'),
        messages=[{'role': 'user', 'content': contenido}],
        temperature=0, max_completion_tokens=8192, response_format={'type': 'json_object'},
    )
    opcion = respuesta.choices[0]
    if opcion.finish_reason != 'stop':
        raise ValueError('La lectura quedó incompleta. No se guardaron operaciones parciales.')
    try:
        datos = leer_json(opcion.message.content)
    except (ValueError, TypeError):
        raise ValueError('La lectura no devolvió una estructura válida. Intente con una imagen más nítida.') from None
    if not isinstance(datos, dict) or not isinstance(datos.get('operaciones'), list):
        raise ValueError('La lectura no contiene una lista de operaciones.')
    if not datos['operaciones'] and not datos.get('saldos_apertura') and not str(datos.get('texto_leido') or '').strip():
        raise ValueError('La lectura no contiene operaciones. No se guardó el caso.')
    return datos


def interpretar_caso_imagen(imagen_file, api_key=None, tasa_impuesto='18'):
    datos = extraer_operaciones(imagen_file, api_key)
    datos['tasa_impuesto_configurada'] = tasa_impuesto
    return generar_asientos(datos)
