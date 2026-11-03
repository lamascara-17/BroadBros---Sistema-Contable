# Importación de texto: PCGE, inventarios y ajustes de cierre

Se reproduce la captura «Cuenta 221 — Proveedores: código incompatible con pasivo»
usando el texto del usuario en `core/testdata/novatech_texto_usuario.txt`.

La validación PCGE antes ocurría al guardar, después de presentar una propuesta
como si no tuviera errores. Ahora se ejecuta también en la validación de cada
asiento del borrador. Los errores se incluyen en los asuntos pendientes.

Los códigos incompatibles se corrigen únicamente cuando el nombre o las compras
del mismo borrador permiten identificar la familia. Un proveedor que financia
equipos de uso propio se identifica con 4654; la misma cuenta corregida se usa
al pagar la deuda. Un proveedor comercial usa 421. Una cuenta que mezcla ambos
orígenes queda para revisión, sin asignarle una familia al azar. No se fusionan
dos cuentas distintas por compartir el nombre genérico «Proveedores».

La fuente de la clasificación es el PCGE del MEF:
https://www.mef.gob.pe/contenidos/conta_publ/documentac/PCGE_2019.pdf

El normalizador solo modifica propuestas nuevas. No cambia códigos, asientos ni
saldos de un caso guardado. Los datos anteriores se preservan ante una validación
fallida. No se desactiva la regla que rechaza 221 como pasivo o 411 como activo.

NovaTech presta servicios; no hay sustento para añadir un inventario de
mercaderías ni su costo de ventas. Se incorpora un control de esa inconsistencia
en este tipo de enunciado, sin inventar ajustes, impuestos ni depreciación.

El texto literal contiene otra contradicción: el encabezado dice octubre de 2026
y las siete operaciones están fechadas en 2025. Se conserva el original y se pide
confirmación. «El año correcto es 2025» o «El año correcto es 2026» permiten indicar
la decisión explícitamente; una pregunta o negación no se toma como confirmación.
Las fechas propuestas deben concordar con la aclaración. Si se pidió revisar antes
de guardar, esa elección se mantiene al completar datos o reintentar el análisis.

## Importes de control (sin ajustes no solicitados)

| Concepto | S/ |
|---|---:|
| Caja | 29.000 |
| Clientes por cobrar | 3.000 |
| Equipos | 12.000 |
| Activos | 44.000 |
| Deuda por equipos | 3.000 |
| Capital | 30.000 |
| Servicios prestados / ventas | 15.000 |
| Alquiler y servicios básicos | 4.000 |
| Utilidad | 11.000 |
| Patrimonio con resultado | 41.000 |

Pruebas adicionales: `python manage.py test core.test_pcge_importacion`. Incluyen
el error de la captura, pago posterior, proveedores ambiguos y separados,
inventarios sin sustento, conservación del caso anterior, aclaración del año,
revisión sin autoguardado, y lectura real de PDF/XLSX con los siete reportes.
Las pruebas del flujo de IA emplean respuestas simuladas y se distinguen de la
comprobación posterior con el proveedor real.

## Mercaderías, materias primas y productos terminados

También se reproduce el caso de `mercaderias_cierre_usuario.txt` con respuestas
simuladas de Groq que usan 411 o 310 para «Inventario», y con ambos códigos en
distintas operaciones. La fuente se pasa al normalizador antes de decidir el
guardado. Solo si el tipo de existencias es inequívoco se corrige su familia; una
cuenta 201 válida se conserva y se reutiliza en la compra y el ajuste. Si existen
varias cuentas compatibles y no se identifica cuál corresponde, se pide revisión.

Las materias primas (24) y los productos terminados (21) no se convierten en
mercaderías (20). Un inventario genérico con código 31 no pasa por ser «activo»;
se necesita determinar la familia de existencias. Los importes no se cambian
para cuadrar la propuesta. El control de inventario final incluye las distintas
familias de existencias y bloquea una diferencia con el saldo físico indicado.

«Al cierre del mes» permite completar una fecha ausente en ajustes identificables
de inventario/costo de ventas o depreciación cuando todas las fechas del texto
determinan un único mes. Se usa su último día real, no un 30/31 arbitrario. Con
varios meses o sin período determinado se conserva el dato pendiente. Una fecha
explícita distinta del cierre se advierte antes de guardar y también se rechaza
en el guardado. La inferencia queda declarada en las convenciones de la propuesta.

Planilla usa la familia 62 y depreciación la 68. Además se revisan los códigos
compartidos entre todos los asientos, no únicamente dentro de cada asiento: si
persisten nombres o clasificaciones incompatibles se señalan las posiciones
reales. El error de una fecha ausente en el ajuste 6/7 no dice «asiento 1».

Pruebas: `python manage.py test core.test_normalizacion_inventario`.

## Alcance y trabajo posterior

Esta corrección no implementa un catálogo exhaustivo de todas las divisionarias
del PCGE ni sustituye todo el análisis de lenguaje por un motor contable nuevo.
El cálculo propuesto de una depreciación todavía requiere revisar costo, tasa,
inicio de uso y criterio temporal. La IA no se considera una fuente de datos.
El siguiente paso de mayor valor sería trasladar más ajustes aritméticos a reglas
deterministas con trazabilidad al enunciado y unificar esas reglas entre texto e
imagen, manteniendo la revisión cuando falte información. Eso se deja separado.

En el ejemplo, un crédito a 15 días señala el vencimiento; no prueba por sí solo
que se pagó. Si el curso asume pago automático al vencimiento, debe declararse
esa convención o confirmarse la cancelación antes de añadir un pago no escrito.
Las pruebas del caso no inventan ese pago. Tampoco se calcula IGV no indicado.

No se incluyen migraciones, cambios de login, infraestructura ni modificaciones
de datos de producción. La instrucción actual es dejar el commit en la rama de
trabajo sin fusionar ni desplegar. Las pruebas de IA son simuladas; la nueva
versión no se ha verificado con Groq en producción porque no se ha desplegado.
