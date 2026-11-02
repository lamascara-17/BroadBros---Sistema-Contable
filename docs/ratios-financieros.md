# Ratios financieros de BroadBros

Ruta: `/ratios-financieros/`. La navegación incluye **Ratios financieros**.

## Datos y alcance

Se incluyen las nueve empresas recibidas: AVGO, NVDA, AMD, ASML, AMAT, LRCX,
INTC, CSCO y KLAC. No se inventa la décima. Se puede añadir desde Datos y fuentes.
Es un grupo académico de semiconductores, equipos y redes; Cisco y el software
de Broadcom limitan la comparabilidad con fabricantes puros de chips.

Los datos iniciales son anuales FY2024 y FY2025 de SEC Company Facts, con corte
de disponibilidad 2026-11-01. No son cotizaciones, TTM ni actualizaciones en vivo.
Los cierres distintos se muestran. Cada partida conserva concepto XBRL,
fecha y accession de su declaración; las derivaciones conservan componentes.
`scripts/build_financial_dataset.py` permite reconstruir el conjunto desde una
carpeta de archivos companyfacts nombrados por ticker. No requiere claves.

NVIDIA es el referente inicial por mayores ventas FY2025 dentro del grupo,
no porque sea automáticamente la mejor en todos los ratios. Es seleccionable.
El promedio del grupo es la media simple de ratios disponibles, incluye la
empresa analizada si pertenece al grupo, y muestra n por indicador. N/D no es 0.

## Método del docente

Referencias: `S7. Alicorp EEFF rentab y dupont COMPLETO (2).xlsx`, hoja Ratios
Financieros; `S5. Alicorp EEFF SOLVECIA Y LIQUIDEZ (2).xlsx`; PPT `S3 y S4 PPT
Análisis de EStados Financieros(2).pdf`, pp. 21–28.

Los 17 indicadores son liquidez corriente, capital de trabajo, prueba ácida,
endeudamiento contable, % endeudamiento, cobertura de intereses, deuda/EBITDA,
días de inventario, días de CxC, días de CxP, ciclo de efectivo, márgenes bruto,
operativo, neto y EBITDA, ROA y ROE. DuPont es complementario.

- Prueba ácida = (caja + clientes) / PC; no (AC − inventario) / PC.
- Promedios de inventario, CxC, CxP, activo y patrimonio: (inicial + final) / 2.
- Días: base de 365. Sin ventas/compras al crédito desglosadas, se usa la
  aproximación de ventas/costo de ventas del taller y se informa expresamente.
- EBITDA = utilidad operativa + D&A; sin compensación en acciones ni otros
  ajustes non-GAAP. No se confunde EBITDA ajustado divulgado con esta fórmula.
- Deuda = CP + LP, según el PPT. Se ofrece variante solo CP; nunca se suman
  indiscriminadamente otros pasivos LP.
- ROA = UO × (1−t) / activo promedio. t=30% es la hipótesis académica del PPT,
  editable para todos los comparables; no se presenta como tasa legal de EE.UU.
- ROE = utilidad neta atribuible / patrimonio promedio atribuible al accionista.
  Endeudamiento usa patrimonio consolidado total, incluidas no controladoras.
- DuPont usa los mismos promedios para que su producto concilie con ROE.
- Capital de trabajo se compara en USD millones. Solo ASML se convierte desde
  EUR al cambio BCE de cierre: 2024 1.0389, 2025 1.1750. Los ratios se calculan
  en moneda nativa; no se mezcla moneda en las medias monetarias.

Fuente FX: https://www.ecb.europa.eu/press/annual-reports-financial-statements/annual/annual-accounts/html/ecb.annualaccounts2025~ba3b593c99.en.html

Cisco queda sin EBITDA y sus tres ratios dependientes hasta completar D&A pura:
el agregado de flujo de caja mezcla «and other»; el dato de depreciación de
propiedad y equipo por sí solo no incluye toda la amortización adquirida.
KLA no presenta subtotal operativo: se deriva de ventas menos costo, I+D,
administración/ventas y deterioro operativo. Componentes documentados en JSON.

## Cierre de verificación de Broadcom FY2025

El 10-K oficial confirma utilidad neta de **23.126 millones USD** en el estado de
resultados (p. 48) y como numerador de utilidad por acciones comunes en la nota 8
(p. 69), con la política de cálculo por acción en p. 57. Fuente:
https://www.sec.gov/Archives/edgar/data/1730168/000173016825000121/avgo-20251102.htm

Por tanto se completa el dato que antes permanecía N/D por falta de verificación:

- Margen neto: 23.126 / 63.887 = **36,20 %**.
- ROE: 23.126 / ((81.292 + 67.678) / 2) = **31,05 %**.
- DuPont utiliza las mismas partidas y concilia con ese ROE.

La excepción revisada está en `core/data/verified_financial_inputs.json` y el
constructor la aplica solamente a esa empresa, periodo, moneda y fecha de
publicación. No habilita `ProfitLoss` como sustituto genérico de utilidad
atribuible en otras empresas. La fuente y la explicación se muestran junto al
dato y se conservan en CSV. Los datos ingresados por el usuario siguen teniendo
precedencia y no se reemplazan por esta corrección estática.

Se contrastaron de nuevo las 17 fórmulas con los resultados guardados de 2016
del Excel S7 original recibido (hoja Ratios Financieros: L3, L6, L8, L12, L15,
L18, L21, L37, L40, L43, L46, L52, L54, L56, L58, L63 y L66), con tolerancia
inferior a 1e-9. Los libros originales solo se leyeron; no se modificaron.

La pantalla distingue utilidad desconocida, cero, pérdida y ganancia. No
concluye ausencia de utilidad a partir de un dato faltante. Si la liquidez no es
calculable tampoco afirma una cobertura numérica. El texto del ROA muestra la
tasa realmente seleccionada; CSV conserva tasa, supuestos y advertencias de
aproximación, además de los 17 valores mostrados. Los datos manuales exportan
su fuente ingresada y su condición de manuales; no se atribuyen a SEC por heredar
el ticker de una compañía ya incluida.

El grupo sigue teniendo las nueve empresas identificadas. No se incorpora una
décima inventada. Los indicadores no calculables de otras empresas permanecen
N/D con su explicación; esta verificación no recertifica cada partida de todos
los informes de las nueve compañías.

## Persistencia e integración

`FinancialRatioPeriod` guarda versiones manuales por ticker y ejercicio. GET no
escribe ni descarga APIs. POST valida números, fechas, CSRF y A=P+patrimonio;
las entradas manuales se identifican como tales y no heredan etiquetas XBRL de
la fuente original. Un campo vacío es desconocido. No modifica CuentaContable,
AsientoContable ni Movimiento. Las importaciones del caso contable tampoco
borran los datos de ratios. La migración 0007 se aplica por build.sh en Render.

Los cinco reportes originales permanecen; el análisis tiene su propia descarga
CSV con filtros, fórmulas y fuentes. No requiere nuevas variables de entorno ni
dependencias de servidor. La persistencia usa la misma base configurada por la
aplicación (DATABASE_URL); no sustituye las garantías de durabilidad del host.

## Verificación

Fixture numérico independiente del Excel del docente, columna 2016: los 17
ratios se contrastan con las celdas calculadas. Además se prueban cierres,
denominadores cero/negativos, datos faltantes, FX, medias, DuPont, selección de
empresas, edición persistente, décima empresa y conservación de los asientos.
