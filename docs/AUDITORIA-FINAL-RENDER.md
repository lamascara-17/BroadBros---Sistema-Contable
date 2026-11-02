# Auditoría final y preparación de Render — 2 de noviembre de 2026

## Dictamen

**No aprobar todavía el despliegue de producción.** Las correcciones quedan preparadas en una rama nueva para revisión. No se fusionó `main`, no se desplegó, no se migró producción y no se cambiaron variables del servicio.

Por indicación del propietario, esta fase trabaja exclusivamente con GitHub y pruebas aisladas. No hay acceso directo autorizado a la configuración privada de Render en esta fase. Una captura histórica o el contenido del repositorio no certifican lo que ejecuta hoy Render.

## Versiones verificadas

- Repositorio: `lamascara-17/BroadBros---Sistema-Contable`.
- Base revisada: `fix/auditoria-integral`, commit `f6f0a14e6c4f5c98dfa24e1320300c05368bc67b`, PR #6 abierto.
- `main` consultado: `d76c4faf818b75f86ff3b68183daeb64577a220c`.
- Rama de preparación: `fix/auditoria-final-render`, sobre la base anterior; el SHA final está en el PR que contiene este documento.
- GitHub Actions de la base: ejecuciones 41379529366 y 41379526314 concluyeron correctamente para `f6f0a14`.
- Rama/commit realmente desplegados, últimos despliegues y logs de Render: **no verificados**. No se infieren de `main`.

## Hallazgos confirmados y correcciones

| Hallazgo reproducido en el código | Corrección |
|---|---|
| La firma de ÑoñoBot dependía del número de asientos y el ID máximo; una edición mantenía ambos. | Revisión persistente por workspace, incrementada por triggers de SQLite/PostgreSQL para INSERT, UPDATE y DELETE de cabeceras, movimientos y cuentas. Incluye bulk_create/update, reemplazos y restauraciones. El incremento se revierte junto con la transacción fallida. |
| Una respuesta iniciada antes de una edición podía guardarse después, con datos antiguos. Dos respuestas simultáneas podían sobrescribir la conversación. | Conversación en BD y confirmación condicional por revisión y secuencia. Una respuesta tardía recibe HTTP 409 sin sobrescribir turnos; la siguiente consulta usa el caso vigente. |
| Intereses y D&A se tomaban del saldo final del Mayor, que el cierre cancela. | Se suman los cargos netos de operaciones del periodo, excluyendo apertura y cierre. El EBITDA y las coberturas se conservan al cerrar resultados. |
| Importación JSON leía todos los bytes, decodificaba el documento y construía otra estructura validada; un límite de 256 MiB no protegía la RAM. | Upload a temporal, parser incremental, límites de profundidad, escalares, tokens, movimientos y estructuras antes de materializar cada asiento. Validación por asiento. Copias grandes en bloques de 64 KiB en BD; descarga FileResponse desde temporal. No se guarda un archivo durable en almacenamiento efímero. |
| El registro manual podía superar los 1.000 asientos/cuentas admitidos por el respaldo. | Límites coherentes en altas manuales e importación y bloqueo transaccional del workspace para las operaciones de alta/reemplazo. Se rechaza antes de reemplazar datos. |
| Los respaldos anteriores a la introducción del catálogo separado podían tener catálogo vacío. | Reconstrucción consistente desde sus movimientos al preparar el archivo, conservando la copia original. Se rechazan clasificaciones contradictorias. |
| `build.sh` aplicaba migraciones en cada compilación. | Build instala y recolecta estáticos, sin migrar. Start comprueba migraciones pendientes y arranca Gunicorn; no las aplica. |
| `DATABASE_URL` presente pero vacía dejaba `DATABASES` sin motor definido. | Se interpreta explícitamente como ausencia de URL y se utiliza SQLite en la ruta configurada; regresión en proceso independiente. |
| Dependencias resueltas podían variar entre compilaciones. | `requirements-render.txt` fija las 40 dependencias verificadas para Linux/Python 3.12. Build y Actions utilizan ese archivo. |

No se modificó el diseño ni se eliminaron módulos. Continúa el acceso público sin login y el aislamiento por sesión anónima. Las rutas antiguas de registro/login siguen redirigiendo al inicio sin crear cuentas.

La revisión crece por modificación de fila, no necesariamente una sola vez por operación de negocio. Su función es detectar cambios confirmados, no numerar documentos. Las copias/archivos temporales se preparan antes de devolver la descarga, por lo que una validación fallida no entrega un JSON parcial.

## Pruebas y evidencia

Entorno aislado Linux/Python 3.12; ninguna prueba escribió en Render ni utilizó su base.

- Base sin modificaciones: **165 pruebas Django correctas**.
- Con correcciones: **176 pruebas** en la matriz final: 165 existentes y 11 regresiones. La ejecución local anterior de 175 pasó en 61,65 segundos. El PR conserva además las ejecuciones remotas del SHA final.
- Pruebas adicionales de las mismas rutas: `makemigrations --check --dry-run`, `pip check`, instalación simulada del lock, `git diff --check` y comprobación de configuración de Gunicorn correctas.
- `collectstatic`: 142 archivos recolectados correctamente.
- `check --deploy` con configuración productiva ficticia: sin errores y dos advertencias HSTS (`security.W005`, `security.W021`). No se activó inclusión de subdominios ni preload sin comprobar el control del dominio y sus consecuencias. Actions no silencia estas advertencias; utiliza `--fail-level ERROR`.
- **Compatibilidad real con una copia del SQLite versionado en `main`:** ese archivo estaba solo en migración 0002, aunque el código tenía migraciones posteriores. Se aplicaron 0003–0014 a una copia temporal: se conservaron exactamente las columnas y valores anteriores de 19 cuentas, 12 asientos y 27 movimientos; las huellas SHA-256 de esas filas no cambiaron. `PRAGMA integrity_check` devolvió `ok`. Esto no es una copia de la BD productiva ni sustituye un ensayo sobre ella.
- **HTTP real con Gunicorn:** alta de cuentas y asiento con CSRF, siete reportes, ambos módulos de ratios, páginas de importación y separación de dos visitantes. Se detuvo y volvió a iniciar el proceso usando la misma SQLite temporal; la sesión y su caso se conservaron. Script: `python scripts/verificar_reinicio.py`.
- **Recursos:** `python scripts/medir_respaldos.py` generó un JSON de **46.683.060 bytes**, 1.000 asientos y 40.000 movimientos; guardó bloques, restauró y reexportó con SHA-256 idéntico. RSS inicial 45.592 KiB, máximo **71.256 KiB**, 19,23 segundos. Es un proceso de benchmark aislado, no una medición del worker de producción ni una garantía de caber en su plan. Las copias antiguas almacenadas como un único JSONField aún requieren materializar ese campo al leerlas; revisar su tamaño antes de recuperarlas en un plan pequeño.
- Actions se amplía a **SQLite y PostgreSQL 16**, incluyendo migraciones, aislamiento, concurrencia, exportaciones y producción. Al ampliar la matriz se detectaron la URL vacía y un doble cierre del streaming en un helper de pruebas que cerraba la conexión PostgreSQL dentro del TestCase; ambos se corrigieron. También se fijó un orden canónico al serializar: PostgreSQL JSONB reorganiza claves, y esa diferencia no debe alterar la huella portable. El resultado remoto del SHA final debe comprobarse en el PR de esta rama antes de aprobar una fusión.

| Función solicitada | Alcance de la comprobación |
|---|---|
| Registro y edición manual | Validaciones, partida doble, CSRF, aislamiento y alta HTTP real. |
| Texto y TXT | Fixtures y mocks del proveedor; persistencia y rechazo atómicos probados. |
| Imágenes | Archivos ficticios y respuestas simuladas; el proveedor real no fue certificado. |
| Cámara/QR | Rutas públicas y contrato del QR probados. El QR abre captura; no transfiere el caso ni una sesión entre dispositivos. Cámara física/permisos pendientes. |
| Siete reportes | Conciliación Diario, Mayor, Comprobación, Resultados, Situación Financiera, Flujos y Patrimonio; aperturas, cierres, impuestos, pérdidas y operaciones no monetarias. |
| PDF/XLSX/CSV | Pruebas leen PDF y libros exportados y comparan resultados; CSV de ratios incluye los 17 indicadores. |
| Ratios | 17 fórmulas contrastadas con el fixture del docente; N/D para datos o denominadores no utilizables. Separación del caso activo y conjunto externo. Regresión de intereses/D&A antes/después del cierre. |
| ÑoñoBot | Caso ficticio, contexto, errores, cambios de versión, rollback, dos respuestas simultáneas y cambio durante la llamada. Llamadas reales al proveedor pendientes. |
| Voz/audio | Validación y respuestas simuladas. Grabación, micrófono, reproducción y servicios reales pendientes de prueba en navegador/dispositivo. |
| Respaldos/restauración | Round-trip grande, catálogos sin movimientos, restauración atómica, fallo de escritura, JSON inválido, cuotas y visitantes separados. |
| Reinicio | Verificado con SQLite local persistente entre dos procesos, no con disco/servicio Render. |

No había navegador/Chromium instalado para un recorrido visual interactivo. Las pruebas HTTP no certifican dispositivos físicos, permisos del navegador ni proveedores externos.

## Ratios y datos externos

El conjunto versionado contiene **nueve** empresas: AVGO, NVDA, AMD, ASML, AMAT, LRCX, INTC, CSCO y KLAC. Falta identificar la décima empresa solicitada por el curso; no se inventó. Incluye periodos, moneda, fuentes y advertencias. La consistencia aritmética y las pruebas se verificaron; no se recertificaron sus cifras contra publicaciones externas en esta fase limitada a GitHub. No deben presentarse como cotizaciones en tiempo real ni como un sector homogéneo sin matices: también incluye equipos y redes/software.

Las cifras del ejercicio no se completan con Broadcom. ROA, rotaciones, coberturas y demás indicadores permanecen N/D si faltan partidas, saldos iniciales, periodo o tasa documentada. N/D no se interpreta como insolvencia o pérdida.

## Base de datos y persistencia: límites de lo verificado

- El código admite PostgreSQL con `DATABASE_URL` y SQLite con `SQLITE_PATH`.
- En `fix/auditoria-integral` no se versiona `db.sqlite3`; `main` sí lo contenía. La copia probada conserva datos históricos, no se propone reemplazar producción con ella.
- Con `RENDER=true`, SQLite sin `SQLITE_PATH` provoca un error de configuración. **Tener SQLITE_PATH no demuestra que la ruta esté montada en un disco persistente.**
- No se verificaron el motor real, disco, montajes, tamaño/plan, backups, retención, concurrencia ni memoria del servicio. Tampoco se verificó PostgreSQL: no se da por existente.
- Los registros históricos con workspace nulo se preservan, pero no se asignan automáticamente al primer visitante. Su recuperación requiere inventario administrativo, copia verificada y asignación explícita al espacio correcto. No se deben publicar globalmente ni adoptar en un GET anónimo.
- Los nuevos respaldos por bloques residen en la BD. Si la BD es efímera, también se pierden: el formato de respaldo no sustituye persistencia de infraestructura.
- Con múltiples workers/instancias, las cuotas basadas solo en caché local no son compartidas. Configurar Redis comprobado o mantener un solo proceso según la carga y el plan.
- Las sesiones anónimas permiten acceso por cookie. La pérdida de esa cookie requiere un respaldo portable para recuperar el caso; no se expone el espacio de otro visitante.

## Variables y comandos propuestos, sin valores secretos

No se puede declarar qué variable falta realmente en Render sin leer su configuración. Verificar nombres y presencia, sin copiar valores a GitHub, chats o logs:

| Configuración | Verificación requerida |
|---|---|
| `SECRET_KEY` | Presente, robusta y estable entre despliegues. No regenerarla si ya existe. |
| `DEBUG` | `false` en producción. |
| `RENDER` | Valor reconocido por la aplicación (`true`). |
| `ALLOWED_HOSTS` | Host público del servicio y dominio propio si corresponde. |
| `WORKSPACE_ISOLATION` | `true`; no desactivarlo en producción. |
| `DATABASE_URL` / `SQLITE_PATH` | Confirmar cuál se utiliza realmente y su persistencia, sin cambiar motor. |
| `REDIS_URL` | Necesario para cuotas compartidas si se usan varios procesos/instancias; verificar conectividad. |
| `GROQ_API_KEY` y modelos `GROQ_*_MODEL` | Necesarios para funciones IA correspondientes; verificar modelo y cuenta con una prueba real aislada. |
| Variables de voz, `GEMINI_API_KEY`, SMTP | Revisar las funciones configuradas y ejecutar pruebas reales específicas; no declarar disponibilidad por tener una variable. |
| `WEB_CONCURRENCY`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT` | La propuesta arranca con 1 worker, 1 thread y 180 s; no es la configuración actual verificada. Medir RAM/carga antes de aumentarlos. |

Comandos propuestos para el servicio, **todavía no aplicados**:

- Build: `bash build.sh` (instalación fijada, estáticos y comprobación; no migra).
- Start: `bash start.sh` (rechaza migraciones pendientes; Gunicorn con `gunicorn.conf.py`).
- Pre-Deploy: no asumir que existe ni que el plan lo admite. Una vez aprobado y con respaldo probado, usar `python manage.py migrate --noinput` en la fase soportada que tenga acceso a **la misma BD** del runtime. En SQLite hay que comprobar el montaje; no ejecutarlo desde un entorno de build que no tenga el disco.

## Plan exacto antes de pedir autorización de producción

1. Revisar el PR de preparación y esperar Actions correctas en ambos motores. Integrar primero en `fix/auditoria-integral` solo después de la revisión; esa fusión también está pendiente.
2. Obtener evidencia de Render: rama, SHA live, despliegues recientes, comandos, plan/RAM, workers, nombres de variables, motor, ruta/montaje y logs depurados. Si aún se desea trabajar exclusivamente por GitHub, el propietario puede aportar estos datos sin secretos. No sustituirlos por suposiciones.
3. Hacer un respaldo consistente de la **BD real**, con sesiones, workspaces, cuentas, asientos, movimientos, ratios y respaldos. PostgreSQL: herramienta de respaldo apropiada y ensayo de restauración. SQLite: API de backup o snapshot consistente que incluya su estado WAL; no copiar a ciegas solo el archivo abierto. Guardar la copia fuera del almacenamiento efímero y comprobar su restauración en una BD independiente.
4. Sobre esa copia, ensayar migraciones 0003–0014 o las que realmente falten, comparar conteos/valores por workspace, integridad y los siete reportes. Revisar respaldos históricos grandes/no compatibles y registros sin workspace. No eliminar ni reasignar datos automáticamente.
5. Confirmar que la ruta SQLite tiene persistencia real, o que la BD PostgreSQL actual la tiene. Si ninguna la tiene, detener el plan: hace falta una propuesta separada de persistencia/migración con respaldo y aprobación. No cambiar de motor por conveniencia.
6. En staging aislado y con presupuesto de memoria equivalente, probar las funciones externas con credenciales autorizadas, cámara/micrófono/audio y backup extremo; medir worker completo, no solo parser. Confirmar cuál es la décima empresa del curso.
7. Presentar el SHA candidato, respaldo verificado, migraciones pendientes, ajustes concretos del servicio y plan de retorno. **Solicitar aprobación antes de fusionar a main, migrar producción, cambiar variables sensibles o desplegar.**
8. Solo tras esa aprobación: coordinar una ventana para evitar escrituras durante la migración, aplicar el procedimiento ensayado en la BD existente, desplegar el SHA aprobado y comprobar SHA live, logs, espacio anónimo, reportes y persistencia tras reinicio. La revisión actual no ejecuta este paso.
9. Retorno: conservar el release y respaldo previos. Ensayar compatibilidad del código anterior con el esquema y su ruta de BD; no volver a introducir un SQLite versionado ni hacer downgrade destructivo automático. Si se requiere restaurar el backup, reconciliar primero las escrituras posteriores para no perder datos nuevos.

**Condición de aprobación:** runtime y persistencia demostrados, restauración productiva ensayada, CI verde y funciones externas probadas. Mientras falte esa evidencia, la recomendación sigue siendo no desplegar.
