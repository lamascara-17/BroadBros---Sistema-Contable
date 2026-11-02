"""Arranque real aislado; nunca utiliza la SQLite del repositorio o de Render."""
import http.client
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from django.test import SimpleTestCase, override_settings
from django.template.loader import render_to_string


class ArranqueAcademicoTests(SimpleTestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory(prefix='broadbros-arranque-')
        self.addCleanup(self.carpeta.cleanup)
        self.raiz = Path(__file__).resolve().parent.parent
        self.db = Path(self.carpeta.name) / 'ejercicio.sqlite3'
        self.entorno = os.environ.copy()
        self.entorno.update(SECRET_KEY='prueba-arranque-no-produccion-abcdefghijklmnopqrstuvwxyz',
            DATABASE_URL='', SQLITE_PATH='', REDIS_URL='', RENDER='true',
            DJANGO_SETTINGS_MODULE='ajustes_arranque',
            PYTHONPATH=self.carpeta.name + os.pathsep + str(self.raiz))
        (Path(self.carpeta.name) / 'ajustes_arranque.py').write_text(
            'from contabilidad.settings import *\n'
            f'DATABASES["default"]["NAME"] = {str(self.db)!r}\n', encoding='utf-8')

    def ejecutar(self, codigo, check=True):
        resultado = subprocess.run([sys.executable, '-c', codigo], cwd=self.raiz,
            env=self.entorno, text=True, capture_output=True, timeout=45)
        if check:
            self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return resultado

    def preparar(self):
        return self.ejecutar('from contabilidad.arranque import preparar_base; preparar_base()')

    def test_crea_tablas_y_repetir_arranque_conserva_ejercicio(self):
        self.preparar()
        self.ejecutar('import django; django.setup(); from core.models import Workspace; '
            'Workspace.objects.create(); from django.contrib.sessions.models import Session; '
            'Session.objects.create(session_key="prueba-persistencia",session_data="dato",expire_date="2030-01-01T00:00:00Z")')
        self.preparar()
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('select count(*) from core_workspace').fetchone()[0], 1)
            self.assertEqual(db.execute('select session_data from django_session').fetchone()[0], 'dato')
            self.assertEqual(db.execute("select count(*) from django_migrations where app='core'").fetchone()[0], 14)

    def test_base_antigua_migra_con_copia_y_conserva_datos(self):
        self.ejecutar('import django; django.setup(); from django.core.management import call_command; '
            'call_command("migrate","core","0002",interactive=False,verbosity=0)')
        with sqlite3.connect(self.db) as db:
            db.execute("insert into core_cuentacontable (codigo,nombre,tipo,subcategoria) values ('101','Caja previa','activo','')")
            db.execute("insert into core_asientocontable (fecha,descripcion,created_at) values ('2009-04-01','Ejercicio anterior','2026-01-01')")
            db.execute("insert into core_movimiento (asiento_id,cuenta_id,tipo,monto) values (1,1,'debe',123.45)")
        self.preparar()
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('select descripcion from core_asientocontable').fetchone()[0], 'Ejercicio anterior')
            self.assertEqual(db.execute('select monto from core_movimiento').fetchone()[0], 123.45)
        copias = list(self.db.parent.glob('ejercicio.sqlite3.antes-migracion-*'))
        self.assertEqual(len(copias), 1)
        with sqlite3.connect(copias[0]) as db:
            self.assertEqual(db.execute('select nombre from core_cuentacontable').fetchone()[0], 'Caja previa')
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_ruta_configurada_no_recibe_migraciones_automaticas(self):
        self.entorno['SQLITE_PATH'] = str(self.db)
        resultado = self.ejecutar('from contabilidad.arranque import preparar_base; preparar_base()', check=False)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('Respaldar y migrar', resultado.stderr)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("select count(*) from sqlite_master where name='core_workspace'").fetchone()[0], 0)

    def test_base_invalida_falla_sin_sustituir_archivo(self):
        contenido = b'archivo invalido: conservar para recuperacion'
        self.db.write_bytes(contenido)
        resultado = self.ejecutar('from contabilidad.arranque import preparar_base; preparar_base()', check=False)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertEqual(self.db.read_bytes(), contenido)

    def test_comando_actual_render_inicia_base_vacia_sin_config_explicita(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            puerto = sock.getsockname()[1]
        self.entorno.update(PORT=str(puerto), ALLOWED_HOSTS='127.0.0.1')
        with tempfile.TemporaryFile(mode='w+') as log:
            proceso = subprocess.Popen([sys.executable, '-m', 'gunicorn', 'contabilidad.wsgi:application'],
                cwd=self.raiz, env=self.entorno, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        cliente = http.client.HTTPConnection('127.0.0.1', puerto, timeout=1)
                        cliente.request('GET', '/ratios-financieros/', headers={'X-Forwarded-Proto':'https'})
                        respuesta = cliente.getresponse()
                        contenido = respuesta.read().decode()
                        cliente.close()
                        self.assertEqual(respuesta.status, 200)
                        self.assertIn('guardado temporal', contenido)
                        self.assertIn('Broadcom', contenido)
                        return
                    except (OSError, http.client.HTTPException):
                        if proceso.poll() is not None:
                            break
                        time.sleep(.1)
                log.seek(0)
                self.fail('No arrancó con el comando de Render: ' + log.read())
            finally:
                proceso.terminate()
                proceso.wait(timeout=10)

    def test_aviso_temporal_no_promete_respaldos_durables(self):
        from core.context_processors import almacenamiento
        with override_settings(RENDER_EPHEMERAL_SQLITE=True):
            html = render_to_string('base.html', almacenamiento(None))
            self.assertIn('copias guardadas dentro del sitio también son temporales', html)
            self.assertIn('/casos-anteriores/actual/', html)
        with override_settings(RENDER_EPHEMERAL_SQLITE=False):
            self.assertNotIn('guardado temporal', render_to_string('base.html', almacenamiento(None)))
