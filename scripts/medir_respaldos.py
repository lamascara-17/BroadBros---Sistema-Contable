"""Benchmark aislado: crea y elimina su propia SQLite temporal, sin entorno productivo.
Ejecutar: python scripts/medir_respaldos.py
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import resource
import json
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
with tempfile.TemporaryDirectory(prefix='broadbros-benchmark-') as carpeta:
    os.environ['DJANGO_SETTINGS_MODULE'] = 'contabilidad.settings'
    os.environ['SQLITE_PATH'] = str(Path(carpeta)/'prueba.sqlite3')
    os.environ.pop('DATABASE_URL',None)
    os.environ.pop('REDIS_URL',None)
    os.environ['RENDER'] = 'false'
    os.environ['SECRET_KEY'] = 'solo-prueba-aislada-no-produccion-abcdefghijklmnopqrstuvwxyz-0123456789'
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import transaction
    from core.models import Workspace, AsientoContable, RespaldoFragmento
    from core.workspaces import actual
    from core.respaldo_stream import guardar_archivo, restaurar_archivo, archivo_actual
    call_command('migrate',verbosity=0)
    token = actual.set(Workspace.objects.create().pk)
    catalogo = [{'codigo':str(10000000000000000000+i),'nombre':f'{i:04}'+('n'*196),'tipo':'activo','subcategoria':'activo_no_corriente'} for i in range(1000)]
    def escribir(f,objeto): f.write(json.dumps(objeto,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode())
    inicio = time.monotonic()
    rss_inicial = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    try:
        with tempfile.TemporaryFile('w+b') as f:
            f.write(b'{"formato":"BROADBROS","version":1,"asientos":[')
            for i in range(1000):
                if i: f.write(b',')
                lineas=[]
                for j in range(40):
                    c=catalogo[(i*40+j)%1000]
                    lineas.append({'codigo':c['codigo'],'nombre':c['nombre'],'tipo_cuenta':c['tipo'],
                        'subcategoria':c['subcategoria'],'tipo_movimiento':'debe' if j<20 else 'haber','monto':'9999999999.99'})
                escribir(f,{'fecha':'2025-01-01','descripcion':'D'*2000,'clase':'operacion','flujo_efectivo':'pendiente',
                    'fecha_cierre':'2025-12-31','fuente':'f'*20000,'observaciones':'o'*10000,'movimientos':lineas})
            f.write(b'],"cuentas":');escribir(f,catalogo);f.write(b'}')
            tamano=f.tell()
            def huella(archivo):
                archivo.seek(0);h=hashlib.sha256()
                while bloque:=archivo.read(65536):h.update(bloque)
                return h.hexdigest()
            esperado=huella(f)
            with transaction.atomic():
                respaldo=guardar_archivo(f)
                restaurar_archivo(f)
            with archivo_actual() as exportado: assert huella(exportado)==esperado
            assert AsientoContable.objects.count()==1000
            assert RespaldoFragmento.objects.filter(respaldo=respaldo).exists()
            print(json.dumps({'bytes_json':tamano,'asientos':1000,'movimientos':40000,
                'rss_inicial_kib':rss_inicial,'rss_maximo_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                'segundos':round(time.monotonic()-inicio,2),'roundtrip_sha256_identico':True}))
    finally: actual.reset(token)
