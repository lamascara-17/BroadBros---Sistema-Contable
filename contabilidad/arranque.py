"""Inicialización del SQLite temporal académico antes de aceptar peticiones."""
import os
import sqlite3
from pathlib import Path
from tempfile import mkstemp


def preparar_base():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'contabilidad.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    if not executor.migration_plan(executor.loader.graph.leaf_nodes()):
        connection.close()
        return
    if not settings.RENDER_EPHEMERAL_SQLITE:
        connection.close()
        raise RuntimeError('Hay migraciones pendientes. Respaldar y migrar la base configurada antes de arrancar.')

    # Nunca borrar o reemplazar una base existente para resolver un error.
    # Copia SQLite consistente (incluye WAL); un error impide el arranque.
    ruta = Path(connection.settings_dict['NAME'])
    connection.close()
    if ruta.exists() and ruta.stat().st_size:
        descriptor, copia = mkstemp(prefix=ruta.name + '.antes-migracion-', suffix='.sqlite3', dir=ruta.parent)
        os.close(descriptor)
        with sqlite3.connect(ruta) as origen, sqlite3.connect(copia) as destino:
            if origen.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('SQLite no pasó la comprobación de integridad; se detuvo el arranque.')
            origen.backup(destino)
        print('Respaldo local previo a migraciones:', copia, flush=True)
    call_command('migrate', interactive=False, verbosity=1)
    call_command('migrate', check=True, verbosity=0)
    connection.close()
