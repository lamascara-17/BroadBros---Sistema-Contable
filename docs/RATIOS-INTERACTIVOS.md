# Laboratorio de ratios y ÑoñoBot financiero

La tabla y su CSV conservan los datos originales y el mismo motor decimal `core.ratios.calculate`. No se añaden modelos, migraciones, servicios ni dependencias de producción.

## Explicación de cada indicador

Los 17 nombres abren un diálogo accesible con fórmula, sustitución numérica, resultado de la tabla, partidas, fuentes disponibles, aproximaciones y comparación con referente/grupo. El capital de trabajo se explica en moneda original y muestra la conversión documentada cuando se compara en USD. Cuando falta conversión se explica N/D. Se calcula sin redondear resultados intermedios; las sustituciones se presentan hasta ocho decimales y los indicadores a dos.

## Simulación parcial y reversible

Controles de ventas, costo de ventas y deuda financiera entre −50% y +50%. El servidor recibe variaciones, selección y huella de datos, nunca importes financieros arbitrarios del navegador. No hay escrituras de partidas, asientos o respaldos. El CSV sigue exportando la tabla original.

- Ventas y costo cambian proporcionalmente. Otros gastos operativos permanecen constantes: variación operativa = variación de ventas − variación de costo de ventas.
- Resultado neto aproximado = resultado neto base + variación operativa × (1 − tasa académica seleccionada). Es un supuesto lineal educativo; no modela impuestos reales, créditos fiscales, nuevas partidas ni causas empresariales.
- Deuda CP y LP cambian en igual proporción; se respeta la base CP/CP+LP aplicada. Intereses, D&A, activos y patrimonio promedio permanecen fijos. La deuda afecta la cobertura, no reconstruye balances ni flujos. Es un escenario parcial, no una operación contable completa ni una proyección de la compañía.
- No se reconstruyen utilidades desconocidas a partir de información incompleta. Los N/D se conservan. El escenario cero reproduce la base de cada empresa/período.
- Las respuestas fuera de orden se descartan mediante secuencia local y cancelación. Se retiran resultados obsoletos en caso de error. Restablecer retorna a cero. La interfaz indica expresamente SIMULACIÓN.

## ÑoñoBot y exposición

En la página comparativa se añade un selector de ámbito: análisis externo de la empresa/período visible o caso contable activo. Las preguntas financieras se responden determinísticamente con el mismo reporte, incluidas comparación, sustituciones, DuPont, fuentes, supuestos, diagnóstico y escenario. No requieren Groq para estos resultados, no inventan causalidad y no representan recomendaciones de inversión. Consultas fuera de esas capacidades explican el alcance disponible. Una referencia breve al indicador anterior se conserva en el navegador; no se comparte conversación ni contexto contable entre visitantes.

La huella incluye compañías y configuración del análisis. Si sus datos cambian antes o durante el cálculo, se devuelve un mensaje para recargar, en vez de una respuesta antigua. El caso contable sigue usando el contexto transaccional anterior y su conversación. Micrófono y audio conservan sus controles y formato de respuesta; los proveedores/dispositivos físicos no se certifican a partir de mocks.

Modo exposición es reversible y admite Escape; conserva advertencias, período, supuestos y N/D. La opción Imprimir/PDF usa la impresión nativa del navegador para los datos originales: oculta edición y simulador y muestra los 17 indicadores, incluso si había un filtro. Los PDF/XLSX contables anteriores no se alteran.

## Validación reproducible

`python manage.py test --noinput` incluye pruebas nuevas de escenarios, fórmulas del Excel, todos los períodos/empresas en cero, N/D, moneda, diferencias en puntos porcentuales, datos obsoletos, CSRF, límites, aislamiento, CSV y separación entre bot financiero/contable. La prueba antigua que exigía el enlace Flujos de efectivo en el menú se adapta a la retirada expresamente solicitada; siguen comprobándose las hojas y las rutas de reportes.

Solo para pruebas de interfaz: Node 24 y jsdom 30.1.3. Instalar jsdom en una carpeta temporal y asignar su node_modules a NODE_PATH; ejecutar `python scripts/verificar_ratios_ui.py`. El script crea una SQLite temporal independiente, obtiene HTML y respuestas reales de Django y comprueba los eventos DOM: 17 diálogos, exposición/Escape, impresión, respuestas fuera de orden, reset, errores, tabla intacta, chat y ámbito. Se ejecuta en Actions para SQLite; Render no instala Node ni jsdom. Es una prueba DOM con diálogos nativos sustituidos, no una certificación de hardware ni de servicios externos.


## Lectura visual y explicaciones breves

El bloque gráfico se coloca antes de la tabla y del simulador, con un acceso “Ver gráficos”. Comparación muestra empresa, referente y promedio del grupo; Evolución muestra los cierres fiscales disponibles, acompañados por una tabla breve con sus valores exactos; Todas las empresas conserva la comparación completa. Las tres vistas usan valores ya calculados por el mismo reporte. Los importes monetarios históricos se convierten a USD con la tasa documentada del cierre correspondiente. Un dato N/D no se dibuja como cero; las pérdidas mantienen su signo. No se incorporan años ni TTM sin datos, ni se infiere una tendencia de largo plazo a partir de dos cierres.

Las unidades se conservan por indicador: veces, días, porcentaje o USD millones. El diseño no copia cifras, fórmulas ni unidades de presentaciones de terceros. El detalle metodológico y las fuentes se mantienen en un desplegable inicialmente cerrado, con una explicación breve visible. Se abren automáticamente al imprimir y se restituye su estado al volver a la pantalla. Las advertencias de inconsistencia del reporte siguen visibles.

Las pruebas de datos verifican las 17 comparaciones, cada cierre histórico, el promedio según grupo y n disponible, la conversión de ASML, N/D, ceros y pérdidas. Las pruebas DOM verifican las tres vistas, selector de indicador, gráfico sin NaN/infinito, detalle plegado y expansión/restauración para impresión, además del laboratorio y ÑoñoBot.
