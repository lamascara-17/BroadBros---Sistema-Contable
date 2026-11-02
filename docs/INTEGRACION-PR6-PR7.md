# Validación conjunta de los PR #6 y #7

## Integridad de la integración

El PR #7 ya está fusionado en `fix/auditoria-integral` mediante `7264042e57f959fb6591b52bc600c8b0132eafe9`. Ese commit tiene el mismo árbol Git (`ad33ac9bb4db48cd92d06608a887176d47f869de`) que el último commit de desarrollo del PR #7, `0b1df40`. La auditoría original del PR #6 (`f6f0a14`) es antecesora de ambos. No hubo pérdida, duplicación de implementaciones ni resolución manual de conflictos que sobrescribiera archivos.

Se verificaron las responsabilidades de views, models, contexto_bot, respaldos, respaldo_stream, ratios_caso, espacio_views, middleware, workspaces, settings, migraciones, plantillas/JS y scripts de arranque. Los modelos, las migraciones 0008–0014, el middleware, los managers, las plantillas/JS y la configuración de producción se mantienen íntegros respecto de la integración original. No se quitó código por considerarlo obsoleto sin prueba de sustitución.

Actions también pasó sobre **7264042 en el PR #6**, no solo sobre el commit del PR #7: [ejecución 41390392023](https://github.com/lamascara-17/BroadBros---Sistema-Contable/actions/runs/41390392023), 176 pruebas por motor.

## Hallazgos reproducidos y correcciones

| Hallazgo | Corrección acotada |
|---|---|
| Importar dos veces el mismo JSON del caso activo creaba cuatro copias iguales. | Comparación exacta por bloques con la copia más reciente del mismo workspace. Reutiliza esa copia si coincide; no elimina ni modifica históricos. Primero se preserva el caso anterior y se restaura, después se conserva el importado, todo en una transacción. |
| D&A registrada por naturaleza y también por destino analítico 9/79 elevaba EBITDA de 11.000 a 11.200 sin modificar el resultado del estado financiero. | Se excluye el destino analítico de D&A/intereses, igual que en el Estado de Resultados. Se conserva la corrección del PR #7 para el cierre. |
| Los estados reconocían la apertura histórica por su descripción, pero los ratios miraban solo `clase`, dejando ROE/periodos sin datos aun con apertura documentada. | Los ratios reutilizan `clase_asiento`, la misma clasificación de apertura/operación/cierre de los estados. |
| La ruta determinista de ÑoñoBot devolvía una respuesta calculada aunque se confirmara un cambio mientras calculaba. | Se verifica la revisión antes/después del cálculo y se devuelve 409 comprensible si cambió. Un rollback mantiene la revisión y no produce ese conflicto. El control transaccional de respuestas IA simultáneas se conserva. |

La comparación de respaldos tiene RAM acotada a bloques de 64 KiB. Solo compara con el último respaldo y solo reutiliza si la representación portable coincide exactamente. No escanea todo el historial ni hace una deduplicación semántica/global. Se conservan el ID y la fecha de la copia reutilizada. Copias distintas, antiguos incompatibles y versiones anteriores permanecen intactos. Los límites siguen siendo 1.000 asientos, 1.000 cuentas, 40 movimientos y 256 MiB.

## Archivos modificados en esta revisión

- `core/views.py`: comprobación de revisión para respuestas deterministas.
- `core/ratios_caso.py`: exclusión analítica y clasificación compartida de aperturas.
- `core/respaldo_stream.py`: reutilización segura y acotada del último respaldo idéntico, dentro de transacción y del mismo workspace.
- `core/espacio_views.py`: orden atómico de restauración y conservación del importado.
- `core/test_integracion_prs.py`: once regresiones adicionales.
- `docs/INTEGRACION-PR6-PR7.md`: este informe.

No se añadieron dependencias ni migraciones. No se modificaron diseño, rutas públicas, autenticación, credenciales, variables, infraestructura ni datos de producción.

## Pruebas

- Base integrada: **176/176** pruebas locales y matriz remota SQLite/PostgreSQL correcta en `7264042`.
- Revisión actual: **187/187** pruebas SQLite locales en 69,48 s. La matriz completa SQLite/PostgreSQL se ejecuta en el SHA final de `fix/auditoria-integral`; consultar Checks del [PR #6](https://github.com/lamascara-17/BroadBros---Sistema-Contable/pull/6) y su descripción actualizada para el resultado remoto y SHA definitivos.
- Las nuevas pruebas cubren duplicación de copias pequeñas/grandes, aislamiento de copias idénticas entre visitantes, conservación de estados distintos, fallo después de restaurar con rollback de datos/copias/conversación, D&A analítica, apertura histórica, cálculo tardío, rollback sin 409 y los 17 valores/fórmulas/observaciones de pantalla frente a ambos CSV.
- Se mantienen las regresiones NovaTech y caso de 2009: partida doble, catálogos PCGE, omisiones/errores, aperturas/cierres, inventarios, siete reportes, PDF y XLSX leídos realmente, ratios/N/D, CRUD, CSRF, importadores, voz/audio simulados, concurrencia y restauraciones.
- `makemigrations --check --dry-run`, `pip check`, `git diff --check` y configuración Gunicorn: correctos.
- `check --deploy`: sin errores y dos advertencias HSTS conocidas, W005/W021. No se activó preload ni cobertura de subdominios sin verificar el dominio.
- Benchmark aislado: JSON de **46.683.060 bytes**, 1.000 asientos y 40.000 movimientos; SHA-256 idéntico después de recuperar y exportar; RSS inicial 45.456 KiB, máximo **72.316 KiB**, 21,19 s. No equivale al consumo completo del servicio Render. Las copias antiguas en un único JSONField aún necesitan materializar ese campo.
- HTTP real/Gunicorn: alta con CSRF, siete reportes, ratios, páginas de importación, dos visitantes aislados y reinicio conservando caso y sesión en SQLite temporal.
- Compatibilidad: se migró nuevamente una copia del SQLite versionado de `main`, desde 0002 hasta 0014. Se conservaron exactamente los valores anteriores de 19 cuentas, 12 asientos y 27 movimientos, comprobados por hash; `integrity_check=ok`. No se utilizó la base productiva.

## Producción y preparación de despliegue

Código preparado para revisión de despliegue, **sin autorización técnica para afirmar que producción está lista**. Trabajar exclusivamente en GitHub no demuestra rama/SHA live, motor, disco, plan, variables ni logs reales de Render. No se asume SQLite ni PostgreSQL en el servidor.

Se conserva el procedimiento de [AUDITORIA-FINAL-RENDER.md](AUDITORIA-FINAL-RENDER.md): inventario real; respaldo consistente y recuperación ensayada sobre una base independiente; ensayo de migraciones y reportes con copia productiva; dimensionamiento de memoria, disco y Gunicorn; verificación de sesiones y Redis si hay múltiples procesos; pruebas externas; aprobación separada antes de cualquier operación productiva. Build no migra y Start rechaza migraciones pendientes.

Acceso anónimo conservado. Los registros históricos sin workspace siguen preservados y no se asignan al primer visitante. No se cambiaron permisos para sortear aislamiento. Las cuotas requieren Redis compartido cuando se escale a múltiples procesos/instancias; la configuración efectiva del servicio sigue pendiente de comprobar.

Cámara/micrófono físicos, reproducción de audio y llamadas reales a Groq, ElevenLabs y SMTP **no están certificados por los mocks**. Los datos comparativos externos son versionados, no cotizaciones vivas; no se inventaron datos ausentes ni se completó una décima empresa no identificada.

No se fusionó a `main`, no se desplegó en Render y no se ejecutaron migraciones productivas. El único destino de cambios de esta revisión es `fix/auditoria-integral` y el PR #6 existente.
