# Descargas de ratios: XLSX, PDF y CSV

Las dos páginas de ratios permiten descargar Excel y PDF manteniendo el CSV:

- `/ratios-financieros/?...&descargar=xlsx` o `descargar=pdf`: conserva empresa,
  referente, ejercicio, grupo, tasa y base de deuda de la comparación aplicada.
- `/ratios-caso/?descargar=xlsx` o `descargar=pdf`: utiliza exclusivamente la
  contabilidad del espacio anónimo actual.

El Excel contiene Resumen, 17 indicadores, Partidas base y Fuentes. Los resultados
son números con formato porcentual o decimal; N/D permanece texto. Incluye fórmulas
explicativas, observaciones y enlaces. Es una descarga de los resultados originales,
no una hoja de simulación que recalcula al editar sus celdas. No incluye escenarios.
Los textos del visitante se guardan como texto y los enlaces solo admiten HTTP/HTTPS.

El PDF se construye con ReportLab como documento vectorial y texto seleccionable,
no capturando el navegador. Tiene resumen y gráfico del margen neto en el comparativo,
dos secciones de ratios agrupados y fuentes con enlaces. Los encabezados de tablas
se repiten si necesitan continuar en otra página; incluye encabezados y paginación.
Las tipografías Fira Mono se incrustan desde los archivos existentes del proyecto.
Las descargas estándar del comparativo tienen cuatro páginas y las del caso tres;
textos extraordinariamente largos pueden ocupar páginas adicionales sin truncarse.

Los valores del comparativo salen de los mismos Decimal calculados por `comparison`;
los del caso salen de `calcular_caso`. No existe un segundo motor financiero en el
exportador. Las partidas base mantienen su moneda; el capital de trabajo comparable
se presenta convertido a USD, como en la pantalla. Las variaciones porcentuales
se muestran en puntos porcentuales. El caso contable conserva importes en PEN.

No requiere migraciones, servicios nuevos ni dependencias adicionales en Render:
reutiliza openpyxl y ReportLab, ya instalados. No escribe partidas contables.
Las respuestas se marcan `private, no-store`.

Pruebas: lectura real de PDF/XLSX, igualdad de los 17 resultados, formatos numéricos,
configuraciones alternativas y conversión monetaria, N/D, acceso sin login, aislamiento
entre visitantes, CSV conservado y textos/enlaces ingresados por usuarios.

Previsualización reproducible con base temporal independiente:

```sh
python scripts/previsualizar_exportaciones_ratios.py /tmp/broadbros-export-review
pdftoppm -png /tmp/broadbros-export-review/comparativo.pdf /tmp/broadbros-export-review/comparativo
```
