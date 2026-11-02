"""Genera descargas reales en una base efímera, sin usar datos de producción.

Uso: python scripts/previsualizar_exportaciones_ratios.py /tmp/broadbros-export-review
"""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Indica un directorio para las cuatro descargas de prueba.')
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    with tempfile.TemporaryDirectory(prefix='broadbros-exportaciones-') as folder:
        os.environ.pop('REDIS_URL', None)
        os.environ.update(DATABASE_URL='', SQLITE_PATH=str(Path(folder)/'aislada.sqlite3'),
                          SECRET_KEY='prueba-exportacion-aislada-abcdefghijklmnopqrstuvwxyz-0123456789',
                          RENDER='false', DJANGO_SETTINGS_MODULE='contabilidad.settings')
        import django
        django.setup()
        from django.core.management import call_command
        from django.test import Client, override_settings
        from core.workspaces import acceso_administrativo
        from core.views import guardar_importacion
        from core.test_estados_financieros import novatech
        call_command('migrate', interactive=False, verbosity=0)
        with acceso_administrativo(), override_settings(WORKSPACE_ISOLATION=False, ALLOWED_HOSTS=['testserver']):
            client = Client()
            for name, url in [('comparativo','/ratios-financieros/'), ('caso','/ratios-caso/')]:
                if name == 'caso': guardar_importacion(novatech())
                for extension in ('xlsx','pdf'):
                    response = client.get(url, {'descargar':extension})
                    assert response.status_code == 200
                    target = output / f'{name}.{extension}'
                    target.write_bytes(response.content)
                    print(target)


if __name__ == '__main__':
    main()
