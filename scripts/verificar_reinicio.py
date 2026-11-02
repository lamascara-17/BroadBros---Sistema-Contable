"""Prueba HTTP con Gunicorn y dos visitantes; solo usa una SQLite temporal."""
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import httpx

raiz = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix='broadbros-http-') as carpeta:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); puerto=sock.getsockname()[1]
    entorno=os.environ.copy()
    entorno.pop('DATABASE_URL',None); entorno.pop('REDIS_URL',None)
    entorno.update(SECRET_KEY='prueba-http-aislada-abcdefghijklmnopqrstuvwxyz-0123456789',
        SQLITE_PATH=str(Path(carpeta)/'datos.sqlite3'), RENDER='false',DEBUG='false',
        ALLOWED_HOSTS='127.0.0.1',PORT=str(puerto),WORKSPACE_ISOLATION='true')
    subprocess.run([sys.executable,'manage.py','migrate','--noinput'],cwd=raiz,env=entorno,check=True,stdout=subprocess.DEVNULL)
    base=f'http://127.0.0.1:{puerto}'
    with open(Path(carpeta)/'gunicorn.log','w+') as log, httpx.Client(base_url=base,follow_redirects=True,trust_env=False) as a, httpx.Client(base_url=base,follow_redirects=True,trust_env=False) as b:
        def iniciar():
            p=subprocess.Popen([sys.executable,'-m','gunicorn','contabilidad.wsgi:application','--config','gunicorn.conf.py'],cwd=raiz,env=entorno,stdout=log,stderr=log)
            for _ in range(100):
                try:
                    if a.get('/').status_code==200: return p
                except httpx.TransportError: pass
                if p.poll() is not None:raise RuntimeError('Gunicorn no arrancó; revisar entorno de prueba.')
                time.sleep(.05)
            p.terminate();p.wait(timeout=10)
            raise RuntimeError('Arranque agotó el tiempo de espera.')
        def csrf(cliente,ruta):
            respuesta=cliente.get(ruta);respuesta.raise_for_status()
            return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',respuesta.text).group(1)
        proceso=iniciar()
        try:
            for codigo,nombre,tipo in [('101','Caja','activo'),('50','Capital','patrimonio')]:
                respuesta=a.post('/cuentas/',data={'csrfmiddlewaretoken':csrf(a,'/cuentas/'),
                    'codigo':codigo,'nombre':nombre,'tipo':tipo,'subcategoria':''})
                respuesta.raise_for_status()
            html=a.get('/asientos/registrar/').text
            # Los IDs de las cuentas se obtienen del formulario servido.
            cuentas=dict((codigo,int(pk)) for pk,codigo in re.findall(r'<option value="(\d+)"[^>]*>\s*(\d+)\s*[-—]',html))
            respuesta=a.post('/asientos/registrar/',data={'csrfmiddlewaretoken':csrf(a,'/asientos/registrar/'),
                'fecha':'2025-01-01','descripcion':'Aporte ficticio HTTP','num_movimientos':'2',
                'cuenta_0':cuentas['101'],'tipo_0':'debe','monto_0':'100',
                'cuenta_1':cuentas['50'],'tipo_1':'haber','monto_1':'100'})
            respuesta.raise_for_status()
            antes=a.get('/casos-anteriores/actual/').json()
            assert len(antes['asientos'])==1
            assert b.get('/casos-anteriores/actual/').json()['asientos']==[]
            rutas=['/reportes/'+p+'/' for p in ('libro-diario','libro-mayor','balance-comprobacion',
                'estado-resultados','balance-general','flujos','patrimonio')]
            rutas+=['/ratios-caso/','/ratios-financieros/','/cargar-texto/','/cargar-imagen/']
            for ruta in rutas: assert a.get(ruta).status_code==200,ruta
            proceso.terminate();proceso.wait(timeout=10)
            proceso=iniciar()
            assert a.get('/casos-anteriores/actual/').json()==antes
            assert b.get('/casos-anteriores/actual/').json()['asientos']==[]
            a.post('/caso/nuevo/',data={'csrfmiddlewaretoken':csrf(a,'/')}).raise_for_status()
            assert a.get('/casos-anteriores/actual/').json()['asientos']==[]
            historial=a.get('/casos-anteriores/').text
            restauracion=re.search(r'action="(/casos-anteriores/\d+/restaurar/)"',historial).group(1)
            a.post(restauracion,data={'csrfmiddlewaretoken':csrf(a,'/casos-anteriores/')}).raise_for_status()
            assert a.get('/casos-anteriores/actual/').json()==antes
            assert b.get('/casos-anteriores/actual/').json()['asientos']==[]
            print('HTTP/Gunicorn: registro con CSRF, 7 reportes, ratios, importadores y dos visitantes: OK. Reinicio, nuevo caso y restauración conservan datos: OK.')
        finally:
            proceso.terminate();proceso.wait(timeout=10)
