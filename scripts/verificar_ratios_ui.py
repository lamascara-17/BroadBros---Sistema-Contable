"""Genera fixtures Django reales en SQLite temporal y comprueba el JS con jsdom.

Solo pruebas: Node 24 y jsdom 30.1.3 deben estar disponibles mediante NODE_PATH.
No necesita esos paquetes en Render ni utiliza las bases configuradas del usuario.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix='broadbros-ratios-dom-') as folder:
    env=os.environ.copy()
    env.pop('DATABASE_URL',None);env.pop('REDIS_URL',None)
    env.update(SECRET_KEY='prueba-dom-aislada-abcdefghijklmnopqrstuvwxyz-0123456789',
        SQLITE_PATH=str(Path(folder)/'prueba.sqlite3'),RENDER='false',DEBUG='false',
        DJANGO_SETTINGS_MODULE='contabilidad.settings',WORKSPACE_ISOLATION='true',
        LAB_DOM_FOLDER=folder)
    code='''
import os,json
from pathlib import Path
import django;django.setup()
from django.core.management import call_command
from django.test import Client,override_settings
from django.test.utils import setup_test_environment
setup_test_environment();call_command('migrate',interactive=False,verbosity=0)
p=Path(os.environ['LAB_DOM_FOLDER'])
with override_settings(ALLOWED_HOSTS=['testserver']):
 c=Client();r=c.get('/ratios-financieros/');assert r.status_code==200
 p.joinpath('page.html').write_bytes(r.content)
 ctx=dict(r.context['ratio_lab_context']);ctx['deuda_base']=ctx.pop('deuda');outputs={}
 for sales in ['0','10','20']:
  response=c.post('/ratios-financieros/laboratorio/',{**ctx,'ventas':sales,'costos':'0','deuda':'0'})
  assert response.status_code==200,response.content
  outputs[sales]=response.json()
 response=c.post('/chatbot/',{**ctx,'context':'ratios_externos','message':'Explícame el ROE'})
 assert response.status_code==200,response.content
 outputs['chat']=response.json();p.joinpath('responses.json').write_text(json.dumps(outputs))
'''
    subprocess.run([sys.executable,'-c',code],cwd=root,env=env,check=True)
    subprocess.run(['node',str(root/'scripts/verificar_ratios_dom.cjs'),str(root),folder],cwd=root,env=env,check=True)
