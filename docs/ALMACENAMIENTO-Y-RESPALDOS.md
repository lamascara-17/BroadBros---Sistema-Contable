# Casos, respaldos y almacenamiento académico

BROADBROS trabaja con un ejercicio activo por visitante, sin login. El recorrido recomendado y las decisiones actuales están en [ENFOQUE-ACADEMICO.md](ENFOQUE-ACADEMICO.md).

## Cambiar o recuperar el ejercicio

- Registrar asientos o importar texto/TXT/imagen trabaja sobre el caso de esa sesión.
- Reemplazar/importar un caso conserva primero el anterior dentro de una transacción.
- “Empezar otro caso” guarda el actual, vacía sus cuentas y asientos y reinicia la conversación. No borra históricos ni datos externos y no afecta a otros visitantes.
- Casos anteriores permite restaurar una copia. El JSON descargado permite trasladarla a otro navegador sin crear una cuenta.
- Si se borran cookies o se cambia de dispositivo, se debe conservar el JSON. Las copias que siguen en la misma base no sustituyen un archivo descargado ni una copia completa de la base.

## JSON sencillo y compatible

Los casos pequeños se guardan como JSON normal. Los límites comunes de escritura y recuperación son 1.000 asientos, 1.000 cuentas y 40 movimientos por asiento. Descripciones de hasta 2.000 caracteres, fuente de hasta 20.000 y observaciones de hasta 10.000 por asiento; archivo de hasta 256 MiB. Son límites de compatibilidad, no tamaños esperados de un ejercicio académico.

El archivo descargado siempre es JSON portable. Si resulta grande, se procesa por partes y su copia interna puede guardarse en bloques de la misma SQLite. Esto evita varias copias completas en RAM y permite leer respaldos ya existentes; no introduce otro servicio. Los históricos incompatibles se conservan y se informa el problema en lugar de recortarlos silenciosamente.

Las descargas validan antes de emitir el archivo. Importar valida antes de reemplazar datos y revierte todas las escrituras si falla. Solo se reutiliza la última copia del mismo visitante cuando coincide exactamente, sin recorrer ni eliminar todo el historial. El caso anterior y el importado siguen siendo recuperables.

## Contexto y seguridad básica

Cada cambio confirmado de asientos, movimientos o cuentas modifica la revisión del caso. Un fallo o rollback conserva su revisión y conversación. Las respuestas tardías no sustituyen un contexto vigente. “Empezar otro caso” también invalida las consultas pendientes aunque el ejercicio ya estuviera vacío.

CSRF, validaciones, aislamiento anónimo y límites básicos de peticiones se mantienen. Un proceso con caché local es suficiente como punto de partida; Redis y colas no forman parte del recorrido académico. El soporte opcional de Redis solo se conserva para instalaciones que ya lo configuraron.

## Persistencia y prevención de pérdida

SQLite necesita un archivo en almacenamiento durable. El archivo local de una computadora puede cumplirlo; la ubicación temporal de un hosting no lo garantiza. Definir `SQLITE_PATH` cambia una ruta, no crea un disco persistente. No se sobrescribe una base existente con el SQLite histórico del repositorio.

Para clases o demostraciones, descargar el caso como JSON antes de cerrar o trasladarlo. Para conservación automática en un servidor, comprobar su almacenamiento y ensayar un respaldo consistente de SQLite antes de actualizar. No cambiar de motor ni de infraestructura por defecto.

No se programan limpiezas de casos, respaldos o sesiones. El comando existente `python manage.py auditar_almacenamiento` es opcional y de solo lectura: informa conteos y tamaños sin descargar conversaciones ni claves. No pertenece al uso diario ni autoriza eliminar registros.
