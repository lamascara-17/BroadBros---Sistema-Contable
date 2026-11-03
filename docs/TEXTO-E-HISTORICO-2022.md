# Texto e histórico de ratios (corte 2026-11-02)

## Importación de texto

Las observaciones de IA se separan y deduplican sin modificar el enunciado ni
los importes. Los bucles de observaciones activan el rescate de lectura ya
existente: los bloques deben reconstruir literalmente el texto original. Si el
rescate falla, se conserva la propuesta inicial utilizable, marcada para revisión;
sin asientos utilizables se informa el error y no se inventan operaciones.

El prompt pide únicamente datos esenciales de operaciones presentes en el caso.
La revisión muestra primero los pendientes principales y permite desplegar el
resto. Ninguna observación se elimina para eludir la validación del guardado.
La opción «Revisar la propuesta antes de guardar» también permite inspeccionar
un caso completo sin escribir asientos; se conserva al confirmar la tasa fiscal.

## Cobertura de ratios

Se reconstruye `core/data/financial_ratios.json` con CompanyFacts oficial de SEC,
usando `scripts/build_financial_dataset.py` y el archivo de excepciones verificadas.
Se conservan las cifras publicadas previamente de FY2024 y FY2025.

- Las nueve empresas tienen FY2022–FY2025.
- NVDA, LRCX, CSCO y KLAC tienen además FY2026 publicado al corte.
- AVGO, AMD, ASML, AMAT e INTC no tienen FY2026 anual publicado al corte.

Un trimestre no sustituye un año. La selección de un año no disponible mantiene
la empresa y avisa qué último año disponible se está mostrando. El grupo y el
referente se calculan por el mismo año fiscal, con el número de observaciones
válidas de cada indicador. Los cierres fiscales difieren entre empresas.

Los gráficos incluyen todos los años disponibles desde 2022 hasta la selección.
Pantalla, CSV, Excel y PDF utilizan el mismo cálculo y período. La conversión
del capital de trabajo de ASML usa EUR/USD de cierre del BCE, incluido 2022 y
2023. Los enlaces a las fuentes aparecen también en Excel y PDF.

El efectivo de Intel 2022/2023 se verifica en el balance consolidado del 10-K
2023 (página 76): 11.144 / 7.079 millones USD, separado de inversiones de corto
plazo. La excepción se aplica únicamente a esos períodos y moneda. No se toma
sin comprobación un agregado de efectivo restringido para otras empresas.

La D&A pura de AVGO 2022 queda N/D: la partida de flujo de efectivo combina
intangibles y derechos de uso. No se sustituye por EBITDA ajustado ni se inventa
una conciliación. CSCO conserva N/D cuando su agregado incluye «otros» conceptos.

## Verificación reproducible

`python manage.py test` ejecuta también `core.test_texto_repeticiones` y
`core.test_ratios_historicos`. Las pruebas del formato de IA usan respuestas
simuladas y no certifican por sí solas disponibilidad de Groq.

`NODE_PATH=<ruta a jsdom> python scripts/verificar_ratios_ui.py` comprueba el
DOM de gráficos, histórico, valores cero/N/D, simulador, exportaciones y tutor.
`python scripts/previsualizar_exportaciones_ratios.py <directorio>` genera
PDF/XLSX reales en SQLite independiente para inspección visual.
