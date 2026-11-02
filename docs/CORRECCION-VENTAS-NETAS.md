# Ventas netas y clasificación del Estado de Resultados

La regresión reproducida consiste en una cuenta de ingresos llamada «Ventas»
con subcategoría `otro_ingreso`. El clasificador anterior daba prioridad a esa
etiqueta: mostraba ventas cero y llevaba el importe a otros ingresos. La utilidad
final podía cuadrar, pero la utilidad bruta, operativa y los márgenes eran incorrectos.

La clasificación identifica ventas ordinarias por familia 70 o nombre inequívoco,
sin transformar donaciones, intereses o enajenaciones de activos de uso en ventas.
Las devoluciones (709) y descuentos comerciales (74) conservan sus saldos deudores
y reducen las ventas netas; el pronto pago (675) permanece financiero.
Los códigos históricos se leen sin renumerar ni modificar los movimientos guardados.
Los borradores nuevos dejan de arrastrar la etiqueta contradictoria de otros ingresos.

También se evita recodificar una «Venta de activo fijo» de 756 a 70, se usa el mismo
clasificador en los ratios del caso y ÑoñoBot distingue utilidad bruta, operativa,
antes de impuestos y neta. Si realmente no hay ventas, se conserva cero y se avisa
cuando existe costo de ventas, sin inventar ingresos.

Regresión ficticia: apertura de caja 5.000 e inventario 1.000 contra capital 6.000;
venta mixta 2.000, costo 600 e intereses 50. Resultado esperado:
ventas 2.000, otros ingresos 0, utilidad bruta/operativa 1.400, resultado neto 1.350,
activo y patrimonio 7.350. Se verifica sin cierre y después del cierre, en pantalla,
PDF, XLSX, ratios/CSV, respuestas deterministas y recuperación JSON.
Es una reproducción del patrón de la captura, no una inspección de su base de datos.

Referencia: PCGE 2019 del MEF, cuentas 70, 74, 75 y 67:
https://www.mef.gob.pe/contenidos/conta_publ/documentac/PCGE_2019.pdf

No requiere migraciones, cambios de motor, variables de entorno ni escrituras en
datos de producción. El análisis comparativo externo no utiliza estos asientos.
