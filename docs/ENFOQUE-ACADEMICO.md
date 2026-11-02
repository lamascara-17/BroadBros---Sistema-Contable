# BROADBROS como herramienta académica

El flujo principal es **ingresar un caso → obtener libros, EEFF y ratios → consultar a ÑoñoBot → exportar**. Un visitante trabaja con un ejercicio activo a la vez, sin registrarse. Otro visitante tiene su propio espacio anónimo.

## Qué se conserva

- Django, SQLite como base predeterminada y estructura existente.
- Registro/edición manual e importación por texto, TXT e imágenes; cámara, QR y voz.
- Siete reportes con una fuente común de cálculos; PDF y Excel, y CSV de ratios.
- Ratios del caso separados de los datos externos; N/D si faltan datos documentados.
- Reemplazo del caso con respaldo previo, restauración JSON y prevención de duplicados consecutivos.
- Transacciones, CSRF, aislamiento anónimo y cuotas básicas de peticiones costosas.
- Revisión persistente del caso y descarte de respuestas antiguas de ÑoñoBot, incluso después de editar, importar, borrar o restaurar. Son correcciones de exactitud, no características de un ERP.

## Simplificación aplicada

1. **Instalación normal sin PostgreSQL ni Redis.** `requirements.txt` y `requirements-render.txt` ya no los instalan. Los controladores se conservan en `requirements-optional.txt` únicamente para instalaciones que ya eligieron esas integraciones. No se provisiona ningún servicio ni se configura una base externa.
2. **Prueba SQLite independiente.** El job SQLite de Actions no inicia un contenedor PostgreSQL ni instala controladores opcionales. Se mantiene un job de compatibilidad PostgreSQL para comprobar que no se rompió el soporte existente; no es un requisito de funcionamiento de la aplicación.
3. **Acción directa “Empezar otro caso”.** Desde el resumen se guarda el ejercicio actual, se vacían solo sus cuentas/asientos y se reinicia el contexto de ÑoñoBot en una transacción. Las copias anteriores y los datos de ratios externos permanecen. Si el respaldo o una escritura falla, se conserva el caso. No crea una cuenta, empresa, organización ni un nuevo espacio anónimo.
4. **Operación sencilla.** Un proceso Gunicorn, SQLite y caché local son el punto de partida existente para el uso académico. No hay razón demostrada para añadir Redis, colas, semáforos distribuidos o más servidores.

## Complejidad que se mantiene por compatibilidad y seguridad

No se borran ni reescriben las migraciones 0008–0014. Mantener el historial de Django evita romper bases existentes; no es necesario añadir otra migración para esta simplificación.

Los ejercicios pequeños ya se guardan como JSON normal. El procesamiento incremental y los bloques de respaldo grande quedan como implementación interna de compatibilidad, sin servicios adicionales. Quitarlos implicaría convertir las copias existentes, arriesgar su recuperación o volver a cargar varias copias de un archivo grande en RAM. No se aumentan los límites de 1.000 asientos, 1.000 cuentas, 40 movimientos y 256 MiB; son techos de compatibilidad, no objetivos de tamaño para ejercicios normales.

La revisión contable y el control de respuestas tardías siguen usando la misma base del ejercicio. Sustituirlos por contar asientos o confiar solo en la sesión reintroduciría los errores que corrigió el PR #7. No dependen de Redis ni de varios servidores.

## Uso normal con SQLite

Instalar `requirements-render.txt`, configurar una `SECRET_KEY` local estable entre arranques en `.env` y aplicar las migraciones a **la base local** antes del primer uso. Django utiliza `db.sqlite3` si no se define otra ruta mediante `SQLITE_PATH`. No configurar `DATABASE_URL` ni `REDIS_URL` para este recorrido. PostgreSQL y Redis son opciones de compatibilidad, no pasos de instalación académica.

En el navegador: registrar/importar el ejercicio, revisar los libros y estados, consultar al bot, exportar y descargar su JSON. Para otro ejercicio, usar “Empezar otro caso”. Para recuperar uno anterior, abrir Casos anteriores o importar su JSON en la nueva sesión. El análisis externo se mantiene independiente.

## Qué sigue pendiente y qué no se promete

- **Persistencia del alojamiento.** SQLite conserva los datos si su archivo reside en almacenamiento durable, por ejemplo en la computadora donde se ejecuta Django. El servicio actual es Render Free, sin disco persistente. Se habilita la demostración temporal autorizada cuando `RENDER=true` y no hay `DATABASE_URL` ni `SQLITE_PATH`. Todas las páginas avisan que el ejercicio y las copias internas pueden perderse; el respaldo durable es el JSON descargado fuera del servidor. No se promete persistencia entre despliegues, suspensión o reemplazo de instancia. [Limitaciones oficiales de Render](https://render.com/docs/free).
- Cámara/micrófono físicos, llamadas reales a Groq/ElevenLabs y SMTP requieren pruebas reales. No se presentan los mocks como prueba del proveedor. La cuenta del proveedor es configuración administrativa, no un login obligatorio para visitantes.
- Los datos externos siguen siendo versionados y sus ausencias siguen como N/D; no se inventó la décima empresa ni información atribuible de AVGO que no está documentada.
- Las dos advertencias HSTS conocidas no se silencian ni se corrigen activando preload/subdominios a ciegas.

La recomendación anterior de añadir una base externa queda fuera del enfoque normal del proyecto. No es necesaria para corregir los cálculos ni para usar BROADBROS académicamente con SQLite durable.

## Arranque en el Render gratuito existente

Se mantienen Build `./build.sh`, Start `gunicorn contabilidad.wsgi:application`, rama `main` y despliegue automático On Commit. `build.sh` es ejecutable y recopila estáticos; no migra la base del build. Gunicorn carga automáticamente `gunicorn.conf.py`. Su hook `on_starting` prepara las tablas **antes** de crear workers o aceptar peticiones, con un worker por defecto.

Solo el perfil temporal anterior aplica automáticamente las migraciones pendientes. Si encuentra una SQLite existente, verifica su integridad y guarda una copia SQLite consistente y privada antes de migrar. Si algo falla se detiene: nunca elimina ni sustituye la base por otra vacía. La copia local de seguridad sigue siendo temporal y no reemplaza el JSON externo. Cuando la base ya está actualizada, no escribe otra copia ni vuelve a migrar.

Una `DATABASE_URL` o `SQLITE_PATH` explícita desactiva esa automatización: el arranque se detiene si faltan migraciones, para mantener el procedimiento de respaldo y aprobación de esa base. No se cambia el motor, no se provisionan discos ni servicios, no se modifican secretos. Las migraciones existentes conservan las filas históricas sin dueño; no se asignan a un visitante nuevo ni se exponen entre sesiones. Para recuperar el ejercicio previo en el espacio anónimo propio se importa su JSON.

Procedimiento de publicación autorizado: conservar el ejercicio previo fuera de Render, comprobar la restauración en SQLite aislada, pasar pruebas/Actions sobre la revisión final y fusionar el PR #6. Comprobar después la misma URL pública y los ratios. Para volver al código anterior, revertir el merge en GitHub tras revisar compatibilidad de esquema; un rollback de código no recupera el archivo efímero de una instancia anterior. El JSON externo permite recuperar el ejercicio en la versión que admita su importación.

Los informes de auditorías anteriores se conservan como evidencia histórica; este documento define el alcance operativo actual.
