# Almacenamiento, respaldos y conversación por caso

Estos controles mantienen el acceso público y el aislamiento por sesión. No requieren cuentas, no eliminan espacios y no se ejecutaron sobre producción.

## Compatibilidad del JSON

La descarga activa y la histórica usan el mismo contrato que la importación: hasta 1 000 asientos, 1 000 cuentas y 40 movimientos por asiento. Descripciones de hasta 2 000 caracteres, fuente de hasta 20 000 y observaciones de hasta 10 000 por asiento. El límite de archivo es 256 MiB; sustituye el límite de 2 MiB que impedía recuperar archivos emitidos por el propio sistema.

La cota contempla los campos completos, Unicode y escapes JSON de hasta seis bytes por carácter. Una prueba mide un asiento extremo y extrapola al catálogo y a los 1 000 asientos; otra crea, descarga, importa y vuelve a descargar el caso completo de 1 000 asientos, 1 000 cuentas y 40 000 movimientos. Compara todo el contenido y sus SHA-256. Los importes, fuentes, notas y fechas se conservan.

Ambas descargas validan el contrato antes de emitir un archivo y no recortan datos para hacerlo caber. Si un catálogo histórico creado fuera de estos límites no es compatible, la pantalla lo informa y conserva sus datos originales; no entrega un JSON que luego resulte imposible importar. Ese histórico requiere una copia administrativa de la base, no dividir o truncar silenciosamente su contabilidad. No se afirma que el formato permita catálogos ilimitados.

La importación conserva CSRF, validación de extensión, estructura y tamaño antes de escribir, y restauración transaccional con respaldo previo. Los archivos subidos grandes pasan al almacenamiento temporal de Django; aun así, la decodificación JSON y los datos del caso consumen RAM. El límite de 256 MiB es una cota de compatibilidad, no una promesa de memoria constante ni de capacidad suficiente en cualquier plan de hosting. Las cuotas independientes son 12 importaciones/restauraciones y 30 descargas por espacio/minuto, con 120 operaciones de respaldo por IP/minuto; Redis comparte contadores entre workers. Las cuotas de IA existentes se mantienen.

La consulta común de movimientos usa JOIN con cuentas y comprueba el espacio de ambos modelos. Evita el límite de profundidad de expresiones de SQLite cuando se precargan 1 000 cuentas. La restauración inserta movimientos por lotes, sin cambiar sus importes u orden.

## Conversación de ÑoñoBot

Las rutas de reemplazo automático por texto/TXT/imagen, revisión confirmada, restauración histórica e importación JSON registran la limpieza de `nonobot_turnos` y su marca de caso con `transaction.on_commit`. Una validación fallida, escritura fallida o rollback no limpia la conversación ni cambia el caso.

La conversación incorpora una firma del espacio y de las cabeceras del caso. Reemplazar/restaurar crea IDs nuevos. Antes de enviar historial a la IA se compara la firma: un turno antiguo reintroducido por una respuesta concurrente o guardado antes de un cambio administrativo no entra al prompt del nuevo caso. Esto complementa la limpieza tras commit y no borra conversaciones de otros visitantes. Las pruebas HTTP de estas rutas usan transacciones reales, de modo que el callback sucede antes de que se guarde la sesión de la respuesta.

## Inventario verificable, sin borrado

Comando administrativo, ejecutado únicamente en la base de pruebas durante este trabajo:

```bash
python manage.py auditar_almacenamiento --dias-minimo 180 --limite 100 --max-sesiones 10000
```

Emite JSON con conteos de espacios, sesiones vigentes/expiradas, cuentas, asientos, movimientos, respaldos y ratios externos. Mide caracteres JSON de respaldos mediante SQL, sin cargar los cuerpos completos en Python; no equivale al tamaño físico del archivo de base de datos. No imprime conversaciones, archivos, claves de sesión ni claves API.

Solo señala para revisión humana espacios anónimos de al menos 180 días que no tienen cuentas, asientos, respaldos ni ratios y no aparecen en una sesión vigente identificada. Usa consultas EXISTS para comprobar las cuatro clases de datos. La fecha de creación no prueba inactividad ni abandono. Una sesión no identificada tampoco prueba que el usuario renunció a sus datos.

Si no puede revisar todas las sesiones dentro de la cota solicitada, o el backend de sesiones no está respaldado por la tabla de Django, no propone candidatos. Nunca borra ni modifica candidatos o sesiones expiradas. No incluye una opción de eliminación y no instala cron ni tareas automáticas.

## Controles de operación propuestos

1. Medir periódicamente tamaño físico de base, archivos temporales, RAM y crecimiento de filas en un entorno administrativo. Conservar informes y comparar tendencias; alertar con margen antes de agotar el disco. Revisar el límite de memoria/tiempo del hosting antes de habilitar archivos cercanos al máximo.
2. Usar almacenamiento persistente, copias de la base cifradas y una restauración ensayada. El JSON del usuario complementa esas copias; no reemplaza un respaldo completo del servicio.
3. En varios workers, usar Redis para cuotas y limitar la concurrencia de importaciones grandes mediante una cola o semáforo compartido. La configuración del proxy debe aceptar los 256 MiB admitidos por la aplicación y limitar tiempo/cuerpo de petición de forma coherente. No se modificó infraestructura ni se desplegó este trabajo.
4. Aplicar alertas y rechazar nuevas operaciones costosas antes de iniciar sus transacciones si falta capacidad, manteniendo lectura/descarga y sin borrar datos para liberar espacio. Una futura cuota de almacenamiento por espacio debe avisarse antes del límite, medirse en bytes y conservar el historial ya existente.
5. Antes de cualquier limpieza futura: copia verificable de la base, listado explícito de IDs, revisión humana, nueva comprobación de sesiones y ausencia de datos dentro de una transacción, y registro de resultado. Empezar solo por espacios vacíos; excluir siempre casos activos y cualquier respaldo recuperable, incluso sin sesión vigente identificada.
6. No programar `clearsessions` ni interpretar automáticamente expiración de sesión como permiso para borrar un workspace. Antes de depurar referencias históricas hay que revisar la recuperación anónima y mantener una copia verificable. Para reducir duplicación de respaldos, estudiar contenido compartido por hash conservando todas las referencias y versiones, sin borrar historial del usuario.

Para limitar el crecimiento de espacios vacíos, se propone estudiar creación diferida hasta la primera operación con datos y una cuota por IP para crear espacios, compatible con visitantes detrás de una misma red. Es un cambio futuro que debe probarse con cámara, QR y navegación antes de activarlo; este trabajo no cambia la asociación por sesión ni elimina espacios para reducir el conteo.
