# Auditoría integral de BROADBROS

Base de trabajo: `d76c4fa` (incluye el módulo de ratios externos). Producción no se utilizó para cargar, modificar o borrar datos. Toda la ejecución utilizó bases SQLite temporales o la base en memoria del runner de Django.

## Hallazgos confirmados y correcciones

| Hallazgo | Corrección | Evidencia |
|---|---|---|
| El caso histórico de 2009 deja inventario 500 pese a declarar 2 500 y carga 5 400 al capital | Auditor determinista antes de guardar, alertas en estados y preservación literal del histórico | Fixture `auditoria_2009.json` extraída leyendo la copia versionada, 12 asientos. Saldo previo 5 900; reducción requerida 3 400. No se aplicó ninguna corrección al histórico |
| Cuadre no garantiza interpretación correcta | Controles de inventario físico, capital debitado sin justificación, duplicados exactos y operaciones omitidas | Pruebas de reglas y de rechazo, conservando registros previos |
| Códigos de otra familia utilizados como PCGE | Validación de familias y coherencia de nombres reconocibles. Normalización de borradores nuevos, nunca de registros históricos | MEF PCGE 2019: https://www.mef.gob.pe/contenidos/conta_publ/documentac/PCGE_2019.pdf |
| Crear y editar aplicaban distintas reglas | Validador común: fecha, 2–40 movimientos, cuentas del espacio, importes finitos positivos, céntimos, límite y cuadre; transacción | Fechas imposibles, NaN, infinitos, negativos, más de dos decimales, cuenta inexistente, cantidad alterada y descuadre |
| Eliminaciones mediante GET | POST y CSRF; pertenencia comprobada mediante el ámbito de datos | GET devuelve 405, sin CSRF 403, identificador ajeno 404 |
| Importación recibía una bandera de limpieza ignorada | Se retira el parámetro de la función y la opción de añadir registros. Guardar siempre reemplaza el caso de ese espacio con respaldo recuperable | Restauración conserva códigos/importes y también cuentas sin movimientos |
| Todos los visitantes compartían libros | Workspace anónimo por sesión, sin adopción ni reasignación al iniciar sesión en Django Admin. Managers filtran cuentas, asientos, movimientos, respaldos y modificaciones del comparativo; sin contexto devuelven vacío | Dos clientes aislados: lectura, edición, eliminación y exportación sin acceso cruzado |
| Consulta sin contexto de espacio | Managers públicos y base devuelven vacío; escrituras mediante manager requieren ámbito. `acceso_administrativo()` es explícito para comandos, fixtures y Django Admin autorizado | Pruebas sin bypass administrativo, contexto restaurado al finalizar cada petición |
| Portabilidad de casos | Descarga JSON del caso activo e históricos, importación validada y restauración transaccional con respaldo previo | Dos sesiones, pérdida de cookie, más de 100 asientos, catálogo sin movimientos, datos maliciosos y rollback |
| Histórico sin propietario | Migración aditiva con propietario nulo, sin renumerar ni borrar; comando explícito de asignación con simulación por defecto | `asignar_historico --workspace UUID`, sin cambios hasta `--confirmar`; opción administrativa antigua `--usuario` conservada |
| Solo cinco estados exportados | Se añaden patrimonio y flujos en pantalla/PDF/XLSX usando los mismos cálculos | Siete hojas y siete secciones; saldos iniciales no documentados N/D |
| Ratios externos no representaban al caso | Nueva ruta `/ratios-caso/`, con CSV propio, unidades PEN, sin aproximaciones de ventas/compras ni apertura inventada | N/D para promedios, impuestos y desgloses ausentes; comparativo externo preservado |
| `ProfitLoss` usado como utilidad atribuible al accionista | Para AVGO FY2025 se conserva fuente y valor excluido; utilidad atribuible y ratios dependientes N/D hasta verificar atribución | Dataset y constructor no confunden esa partida consolidada con utilidad atribuible; no se inventó una cifra sustituta |
| Consultas del bot podían recalcular saldos por IA | Respuestas deterministas de utilidad, balance y controles del caso; contexto financiero y cuatro turnos privados para otras consultas | Mock verifica importes reales, continuidad y ausencia de llamada al proveedor para saldos |
| Consumo de IA sin control | Acceso libre; cuotas por espacio/endpoint/minuto y por IP; Redis para compartir cuota entre workers | Sin bloqueos de autenticación. 429 JSON para APIs y HTML amigable para formularios |
| Errores completos SMTP/API | Mensajes externos genéricos; fallo SMTP devuelve PDF descargable con estado `X-Report-Email-Status: failed` | Excepción con dato privado no aparece en respuesta; PDF vuelve a abrirse |
| DB versionada, secreto conocido y hosts abiertos | SQLite desversionada, SECRET_KEY obligatoria fuera de pruebas/desarrollo, hosts explícitos, cookies/HTTPS en Render | `check --deploy`, migraciones y pruebas de aislamiento |
| Freeze contenía versiones no reproducibles con el entorno disponible | Dependencias directas UTF-8 compatibles y Python 3.12.14 | Instalación desde requirements y ejecución local |

## Contabilidad del caso A

Este caso tiene **seis** operaciones. No incluye el gasto de servicios básicos de 1 000 de otra variante anterior.

- Asientos: 6.
- Sumas Debe y Haber: 67 000 cada una.
- Caja: 30 000.
- Clientes: 3 000.
- Equipos: 12 000.
- Proveedores: 3 000.
- Capital: 30 000.
- Resultado: 12 000.
- Activo: 45 000; pasivo: 3 000; patrimonio con resultado: 42 000.

El caso B necesita revisar la contrapartida del ajuste de 3 400 según el enunciado original (costo de ventas, diferencias o pérdidas documentadas). El software señala la inconsistencia y bloquea el nuevo guardado incorrecto; no transforma automáticamente un ajuste contra capital en gasto.

## Pruebas ejecutadas

- Suite previa sin cambios: 123 pruebas correctas.
- CI en `.github/workflows/django-tests.yml`; resultado remoto del nuevo commit verificado por separado al terminar.
- Suite final: **149 pruebas correctas** (Python 3.12.14, Django 5.2, base temporal/en memoria).
- Casos A–H: reglas, importación de texto/TXT/imagen simulada, impuestos explícitos, faltantes, importes inválidos, 17 indicadores, contexto del bot y voz con servicios simulados.
- Clientes HTTP anónimos con aislamiento real: módulos, enlaces internos resueltos, formularios POST con CSRF y confirmación, registro/edición/borrado, texto/TXT/imagen y revisión, siete reportes PDF/XLSX, CSV, bot, voz y audio. Dos visitantes no pueden leer, editar, eliminar, descargar o restaurar datos ajenos.
- Mismo usuario administrativo en dos dispositivos conserva espacios públicos independientes; salir de Django Admin preserva el espacio anónimo anterior. Las fixtures históricas emplean `acceso_administrativo()` explícito; las nuevas pruebas públicas no usan ese bypass. No son pruebas de clics de todos los navegadores.
- PDF y XLSX generados y reabiertos: sin movimientos (7 páginas/7 hojas), NovaTech seis asientos (9 páginas/7 hojas), caso de 60 asientos (22 páginas/7 hojas).
- PDF renderizado con Poppler e inspeccionado: situación financiera, patrimonio y flujos. Se corrigió recorte de importes en la tabla nueva de flujos.
- Generación con razón social con `Ñ`, `&` y otros caracteres. Textos Excel se mantienen como texto, nunca fórmulas. Los nombres de descarga se normalizan.
- Migraciones 0008, 0009 y 0010 aplicadas en SQLite temporal.
- `makemigrations --check --dry-run`: sin cambios pendientes.
- Dependencias instaladas desde `requirements.txt`; `collectstatic` correcto.
- `check --deploy` con configuración de producción simulada: sin errores, dos advertencias sobre HSTS de subdominios y preload, mantenidos desactivados porque el proyecto no controla todos los subdominios del dominio compartido.

## Archivos y organización

- Datos y seguridad: `models.py`, `workspaces.py`, `middleware.py`, migraciones 0008/0009/0010, `espacio_views.py`, `respaldos.py`, comando `asignar_historico`, configuración, importación y descarga de respaldos.
- Validación: `validacion_contable.py`, `views.py`, `orientacion.py`, `importacion_general.py`.
- Informes: `reporte_utils.py`, `exportacion.py`, plantillas PDF/patrimonio/flujos.
- Ratios: `ratios.py`, `ratios_caso.py`, `ratio_views.py`, dataset/construcción SEC y plantillas.
- Bot: `bot_calculos.py` y contexto en `views.py`.
- Pruebas nuevas: `test_auditoria_integral.py`, `test_acceso_anonimo.py`; pruebas anteriores actualizadas solo donde cambió el contrato (POST, siete estados, PCGE nuevo y datos de atribución no verificados).

## Despliegue seguro en Render

No se debe fusionar y desplegar sin preparar la persistencia y la asignación del histórico.

1. Crear un respaldo verificable de la base **de producción** por los mecanismos del administrador. Este trabajo no ejecutó esa acción ni abrió sus datos.
2. Mantener el valor secreto vigente de `SECRET_KEY` en el entorno. No escribirlo en GitHub. Configurar `ALLOWED_HOSTS` con el dominio real.
3. Mantener la conexión persistente existente mediante `DATABASE_URL`, o configurar `SQLITE_PATH` dentro de un disco persistente de Render. El arranque rechaza Render+SQLite sin esa ruta explícita. No copiar la DB del repositorio encima de producción.
4. Opcional/recomendado para varios workers: `REDIS_URL`. Sin Redis, la cuota usa caché local y se aplica por proceso; no es una protección global distribuida.
5. Mantener `WORKSPACE_ISOLATION=true`. Toda la aplicación pública funciona sin cuenta, incluso IA, importación y audio. La antigua bandera de autenticación se eliminó. Django Admin mantiene su autenticación propia para tareas administrativas.
6. Ejecutar migraciones en staging/restauración de la copia de seguridad. Las columnas de workspace dejan el histórico sin propietario y fuera del acceso público.
7. En un espacio anónimo vacío destinado al histórico, el administrador puede obtener su UUID de la sesión y ejecutar `python manage.py asignar_historico --workspace UUID` para simular. Solo después del respaldo y de verificar el destino, ejecutar con `--confirmar`. El comando rechaza destinos con datos y no cambia códigos, nombres ni importes. La opción administrativa `--usuario` es de compatibilidad: no vincula automáticamente el acceso público a ese usuario.
8. Verificar el espacio anónimo seleccionado, libros, PDF y descarga/importación de respaldos en otra sesión antes de habilitar tráfico. `cargar_prueba` exige `--workspace UUID`, respalda el caso anterior y no modifica otros espacios.
9. El build ejecuta instalación, `collectstatic` y `migrate`. El servidor puede arrancar con `python -m gunicorn contabilidad.wsgi:application` según la configuración de Render.

La eliminación de `db.sqlite3` del índice Git no borra la copia desplegada ni purga archivos de commits antiguos. La asignación histórica no se ejecuta durante migraciones ni durante el build.

## Límites y pendientes reales

- No se realizaron pruebas con la API real de Groq, SMTP real ni ElevenLabs: no había credenciales de prueba. Se simularon sus respuestas y errores.
- Cámara, micrófono y QR necesitan comprobación manual final en los dispositivos del usuario. No se afirma haberlos probado en un teléfono.
- Las 17 fórmulas se contrastan con la fixture del taller y las pruebas del dataset. No se volvió a descargar y auditar cada partida de todos los filings SEC. La atribución del resultado AVGO FY2025 sigue pendiente; se muestra N/D.
- El chequeo PCGE implementado cubre familias y correspondencias reconocibles. No equivale a una certificación exhaustiva de todas las divisionarias, políticas contables o casos NIIF.
- Los controles de omisiones y fuente son deterministas pero no prueban la interpretación semántica completa de cualquier ejercicio. Los campos desconocidos deben seguir en revisión.
- Una sesión anónima que pierde sus cookies puede perder el acceso a su espacio. Se explica en Casos anteriores: descargar el JSON antes de cambiar de dispositivo o borrar cookies, e importarlo en la sesión nueva. No se exige ni ofrece registro para recuperar casos. El archivo permite acceder a su contenido: debe conservarse en privado. Importación acotada a 2 MB, 1 000 asientos y 1 000 cuentas; validación antes de cualquier escritura y respaldo previo dentro de la transacción.
- El estado de flujos puede quedar provisional con partidas sin clasificación; el patrimonio muestra N/D de apertura cuando no se documenta. No se rellenan datos para aparentar estados completos.
- Para un catálogo didáctico/histórico se preservan los registros originales y se muestran advertencias. Las nuevas altas/importaciones se validan como familias PCGE, sin una conversión masiva de historia.

Las cuotas públicas actuales son 12 consultas de chat y 6 solicitudes de voz, audio, importación o revisión por espacio/endpoint/minuto, además de 120 solicitudes de IA por IP/minuto. Se utiliza REMOTE_ADDR, sin confiar en X-Forwarded-For suministrado por visitantes. Si el proxy concentra visitantes en una sola dirección, comparten ese límite de IP; Redis permite compartir contadores entre procesos. CSRF, validación de archivos y claves exclusivamente en el servidor se mantienen.
