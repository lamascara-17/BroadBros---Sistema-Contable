"""Revisión transaccional incluso para bulk_create/update y SQL administrativo.

El incremento pertenece a la misma transacción que la modificación: un rollback
revierte ambos. No modifica importes ni elimina información histórica.
"""
from django.db import migrations

TABLES = ('core_asientocontable', 'core_movimiento', 'core_cuentacontable')


def scope(table, row):
    if table == 'core_movimiento':
        return f'(SELECT workspace_id FROM core_asientocontable WHERE id = {row}.asiento_id)'
    return f'{row}.workspace_id'


def install(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor not in ('sqlite', 'postgresql'):
        raise RuntimeError('La versión contable requiere SQLite o PostgreSQL.')
    for table in TABLES:
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            name = f'bb_revision_{table}_{event.lower()}'
            rows = ('NEW',) if event == 'INSERT' else ('OLD',) if event == 'DELETE' else ('OLD', 'NEW')
            scopes = ', '.join(scope(table, row) for row in rows)
            update = f'UPDATE core_workspace SET revision_contable = revision_contable + 1 WHERE id IN ({scopes});'
            if vendor == 'sqlite':
                schema_editor.execute(f'CREATE TRIGGER {name} AFTER {event} ON {table} BEGIN {update} END')
            else:
                schema_editor.execute(f'CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {update} RETURN NULL; END; $$')
                schema_editor.execute(f'CREATE TRIGGER {name} AFTER {event} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()')


def uninstall(apps, schema_editor):
    for table in TABLES:
        for event in ('insert', 'update', 'delete'):
            name = f'bb_revision_{table}_{event}'
            if schema_editor.connection.vendor == 'postgresql':
                schema_editor.execute(f'DROP TRIGGER IF EXISTS {name} ON {table}')
                schema_editor.execute(f'DROP FUNCTION IF EXISTS {name}()')
            else:
                schema_editor.execute(f'DROP TRIGGER IF EXISTS {name}')


class Migration(migrations.Migration):
    dependencies = [('core', '0011_version_contable_bot')]
    operations = [migrations.RunPython(install, uninstall)]
