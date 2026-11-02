"""Pruebas HTTP públicas con el aislamiento real, sin bypass administrativo."""
import json
import os
from copy import deepcopy
from html.parser import HTMLParser
from io import BytesIO, StringIO
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
import httpx
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse, resolve
from openpyxl import load_workbook
from pypdf import PdfReader
from .audio_respuesta import datos_audio
from .importacion_general import normalizar_borrador
from .models import AsientoContable, CuentaContable, Movimiento, RespaldoCaso, FinancialRatioPeriod
from .test_estados_financieros import novatech
from .test_ciclo_contable import imagen
from .views import guardar_importacion
from .workspaces import actual, acceso_administrativo


class Elementos(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.forms=[]; self.links=[]; self.inputs=[]; self.form=None
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='a': self.links.append(attrs.get('href',''))
        if tag=='form':
            self.form={**attrs,'inputs':[]}; self.forms.append(self.form)
        if tag=='input':
            self.inputs.append(attrs)
            if self.form is not None: self.form['inputs'].append(attrs)
    def handle_endtag(self,tag):
        if tag=='form':self.form=None


@override_settings(WORKSPACE_ISOLATION=True, GROQ_API_KEY='clave-falsa-de-prueba')
class AccesoAnonimoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a,self.b=Client(),Client()
        for c in (self.a,self.b): c.get(reverse('index'))

    def sembrar(self, cliente, datos=None):
        token=actual.set(cliente.session['workspace_id'])
        try: guardar_importacion(datos or novatech())
        finally: actual.reset(token)

    def diario(self, cliente):
        return list(cliente.get(reverse('libro_diario')).context['asientos'])

    def respaldo(self, cliente):
        return cliente.get(reverse('descargar_actual')).json()

    def subir(self, cliente, contenido):
        archivo=SimpleUploadedFile('caso.json',json.dumps(contenido).encode(),content_type='application/json')
        return cliente.post(reverse('importar_respaldo'),{'respaldo':archivo},follow=True)

    def test_modulos_navegacion_camara_qr_y_exportaciones_publicos(self):
        self.sembrar(self.a)
        nombres=('index','gestionar_cuentas','registrar_asiento','cargar_texto_diario','cargar_imagen_diario',
                 'libro_diario','libro_mayor','balance_comprobacion','estado_resultados','balance_general',
                 'estado_patrimonio','estado_flujos','ratios_caso','ratios_financieros','reporte_completo','respaldos')
        for c in (self.a,self.b):
            for nombre in nombres:
                with self.subTest(cliente=c,nombre=nombre):
                    r=c.get(reverse(nombre),follow=True);self.assertEqual(r.status_code,200)
                    html=r.content.decode();elementos=Elementos(html)
                    self.assertNotIn('Iniciar sesión',html)
                    for link in elementos.links:
                        partes=urlsplit(link)
                        if partes.path.startswith('/') and not partes.netloc and not partes.path.startswith('/static/'):
                            resolve(partes.path)
                            self.assertNotIn('/eliminar/',partes.path)
                    for form in elementos.forms:
                        if form.get('method','get').lower()=='post':
                            self.assertTrue(any(i.get('name')=='csrfmiddlewaretoken' for i in form['inputs']))
        html=self.a.get(reverse('cargar_imagen_diario')).content.decode()
        self.assertIn('QR',html)
        campos=Elementos(html).inputs
        self.assertTrue(any(i.get('capture')=='environment' and i.get('type')=='file' for i in campos))
        self.assertTrue(any(i.get('type')=='file' and 'capture' not in i for i in campos))
        for c in (self.a,self.b):
            x=c.post(reverse('reporte_completo'),{'formato':'excel'})
            self.assertEqual(len(load_workbook(BytesIO(x.content)).sheetnames),7)
            pdf=c.post(reverse('reporte_completo'),{'formato':'pdf'})
            self.assertGreaterEqual(len(PdfReader(BytesIO(pdf.content)).pages),7)
            csv=c.get(reverse('ratios_caso')+'?descargar=csv')
            self.assertEqual(csv.status_code,200);self.assertIn('text/csv',csv['Content-Type'])
        self.assertEqual(len(self.diario(self.b)),0)
        self.assertNotEqual(self.a.session['workspace_id'],self.b.session['workspace_id'])

    def test_importar_texto_txt_imagen_y_revision_sin_cuenta(self):
        texto='\n'.join(f"El {a['fecha'][8:10]}/10/2025: {a['descripcion']}" for a in novatech())
        borrador=normalizar_borrador({'asientos':novatech(),'pendientes':[],'supuestos':[]})
        with patch('core.importacion_general.proponer_caso_general',return_value=borrador):
            self.assertRedirects(self.a.post(reverse('cargar_texto_diario'),{'texto_caso':texto}),reverse('libro_diario'))
            archivo=SimpleUploadedFile('caso.txt',texto.encode(),content_type='text/plain')
            self.assertRedirects(self.b.post(reverse('cargar_texto_diario'),{'archivo_texto':archivo}),reverse('libro_diario'))
        self.assertEqual(len(self.diario(self.a)),7);self.assertEqual(len(self.diario(self.b)),7)
        with patch('core.ai_diario.extraer_operaciones',return_value={'texto_leido':texto}), \
             patch('core.ciclo_contable.generar_asientos',side_effect=ValueError('Analizar texto')), \
             patch('core.importacion_general.proponer_caso_general',return_value=borrador):
            self.assertRedirects(self.a.post(reverse('cargar_imagen_diario'),{'foto_camara':imagen()}),reverse('libro_diario'))
        incompleto=deepcopy(borrador);incompleto['pendientes']=['Indique la fecha de cierre.']
        with patch('core.importacion_general.proponer_caso_general',return_value=incompleto):
            r=self.b.post(reverse('cargar_texto_diario'),{'texto_caso':texto})
        self.assertContains(r,'Revisar ejercicio')
        forms=Elementos(r.content.decode()).forms
        revision=next(f for f in forms if any(i.get('name')=='revision_token' for i in f['inputs']))
        datos={i['name']:i.get('value','') for i in revision['inputs'] if i.get('type')=='hidden'}
        datos['accion']='reintentar'
        with patch('core.importacion_general.proponer_caso_general',return_value=incompleto):
            self.assertEqual(self.b.post(reverse('revisar_importacion'),datos).status_code,200)
        self.assertEqual(len(self.diario(self.b)),7)

    def test_registro_edicion_y_todos_los_borrados_post_csrf_aislados(self):
        seguro=Client(enforce_csrf_checks=True);seguro.get(reverse('gestionar_cuentas'))
        csrf=seguro.cookies['csrftoken'].value
        for codigo,nombre,tipo in [('101','Caja','activo'),('50','Capital social','patrimonio')]:
            r=seguro.post(reverse('gestionar_cuentas'),{'csrfmiddlewaretoken':csrf,'codigo':codigo,'nombre':nombre,'tipo':tipo})
            self.assertEqual(r.status_code,302)
        cuentas=seguro.get(reverse('registrar_asiento')).context['cuentas']
        ids={c.codigo:c.pk for c in cuentas}
        datos={'csrfmiddlewaretoken':csrf,'fecha':'2025-10-01','descripcion':'Aporte manual','num_movimientos':'2',
               'cuenta_0':ids['101'],'cuenta_1':ids['50'],'tipo_0':'debe','tipo_1':'haber','monto_0':'100','monto_1':'100'}
        self.assertRedirects(seguro.post(reverse('registrar_asiento'),datos),reverse('libro_diario'))
        pk=self.diario(seguro)[0].pk
        for pagina in ('registrar_asiento','libro_diario','gestionar_cuentas'):
            elementos=Elementos(seguro.get(reverse(pagina)).content.decode())
            forms=[f for f in elementos.forms if '/eliminar/' in f.get('action','')]
            self.assertTrue(forms)
            for f in forms:
                self.assertEqual(f.get('method','').lower(),'post')
                self.assertIn('confirm(',f.get('onsubmit',''))
                self.assertTrue(any(i.get('name')=='csrfmiddlewaretoken' for i in f['inputs']))
        for nombre,valor in [('eliminar_asiento',pk),('eliminar_cuenta',ids['101'])]:
            url=reverse(nombre,args=[valor])
            self.assertEqual(seguro.get(url).status_code,405)
            self.assertEqual(seguro.post(url,{}).status_code,403)
            self.assertEqual(self.b.post(url,{}).status_code,404)
        self.assertEqual(self.b.post(reverse('editar_asiento',args=[pk]),datos).status_code,404)
        self.assertEqual(seguro.post(reverse('editar_asiento',args=[pk]),{**datos,'descripcion':'Editado'}).status_code,302)
        self.assertEqual(self.diario(seguro)[0].descripcion,'Editado')
        self.assertEqual(seguro.post(reverse('eliminar_asiento',args=[pk]),{'csrfmiddlewaretoken':csrf}).status_code,302)
        self.assertEqual(seguro.post(reverse('eliminar_cuenta',args=[ids['101']]),{'csrfmiddlewaretoken':csrf}).status_code,302)
        self.assertEqual(self.diario(self.b),[])

    def test_backup_portable_reemplazo_rollback_y_recuperacion_sin_cookie(self):
        self.sembrar(self.a);original=self.respaldo(self.a)
        self.assertEqual(len(original['asientos']),7)
        self.sembrar(self.b,novatech()[:1])
        self.assertContains(self.subir(self.b,original),'Respaldo importado')
        self.assertEqual(self.respaldo(self.b),original)
        # Hay copia del caso de un asiento previo al reemplazo.
        historial=self.b.get(reverse('respaldos')).context['respaldos']
        viejo=next(r for r in historial if len(r.datos)==1)
        self.assertEqual(self.a.get(reverse('descargar_respaldo',args=[viejo.pk])).status_code,404)
        self.assertEqual(self.a.post(reverse('restaurar_respaldo',args=[viejo.pk])).status_code,404)
        self.assertEqual(self.b.get(reverse('restaurar_respaldo',args=[viejo.pk])).status_code,405)
        self.b.post(reverse('restaurar_respaldo',args=[viejo.pk]))
        self.assertEqual(len(self.diario(self.b)),1)
        self.assertEqual(len(self.diario(self.a)),7)
        self.a.cookies.clear();self.assertEqual(self.diario(self.a),[])
        self.assertContains(self.subir(self.a,original),'Respaldo importado')
        self.assertEqual(self.respaldo(self.a),original)
        antes=self.respaldo(self.a)
        with patch('core.respaldos.CuentaContable.objects.create',side_effect=ValueError('No se pudo restaurar')):
            self.subir(self.a,original)
        self.assertEqual(self.respaldo(self.a),antes)
        self.assertContains(self.a.get(reverse('respaldos')),'cookies')

    def test_backup_invalido_no_altera_datos_ni_expone_campos(self):
        self.sembrar(self.a);original=self.respaldo(self.a)
        variantes=[{'workspace_id':self.b.session['workspace_id']}, {'version':True}, {'cuentas':[{'codigo':'101','nombre':'Caja','tipo':[]}]},
                   {'asientos':[{'fecha':'2025-01-01','descripcion':'x','movimientos':[{},{}],'clase':[]}]},
                   {'cuentas':[{**original['cuentas'][0],'owner':1}]}]
        for variacion in variantes:
            with self.subTest(variacion=variacion):
                r=self.subir(self.a,{**original,**variacion})
                self.assertEqual(r.status_code,200);self.assertEqual(self.respaldo(self.a),original)
        for nombre,contenido in [('caso.json',b'{'),('caso.json',b'\xff'),('caso.exe',b'{}'),('caso.json',b'x'*(2*1024*1024+1))]:
            r=self.a.post(reverse('importar_respaldo'),{'respaldo':SimpleUploadedFile(nombre,contenido)},follow=True)
            self.assertEqual(r.status_code,200);self.assertEqual(self.respaldo(self.a),original)
        seguro=Client(enforce_csrf_checks=True)
        self.assertEqual(seguro.post(reverse('importar_respaldo'),{}).status_code,403)

    def test_bot_voz_audio_publicos_y_cuotas_independientes(self):
        self.sembrar(self.a)
        self.assertEqual(self.a.post(reverse('chatbot_api'),{'message':'¿Cuál es mi utilidad neta?'}).json()['status'],'calculated')
        self.assertEqual(self.b.post(reverse('chatbot_api'),{'message':''}).status_code,400)
        with patch('core.voz.Groq') as groq:
            groq.return_value.audio.transcriptions.create.return_value=SimpleNamespace(text='Explica el balance')
            for c in (self.a,self.b):
                r=c.post(reverse('transcribir_voz'),{'audio':SimpleUploadedFile('voz.webm',b'audio',content_type='audio/webm')})
                self.assertEqual(r.json(),{'texto':'Explica el balance'})
        with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'falsa','NONOBOT_VOICE_ID':'voz'}), patch('core.audio_respuesta.httpx.post') as voz:
            voz.return_value=httpx.Response(200,content=b'mp3',headers={'content-type':'audio/mpeg'},request=httpx.Request('POST','https://api.elevenlabs.io'))
            for c in (self.a,self.b):
                r=c.post(reverse('respuesta_audio'),{'token':datos_audio('Respuesta')['audio_token']})
                self.assertEqual(r.status_code,200)
        cache.clear()
        for _ in range(12): self.a.post(reverse('chatbot_api'),{'message':''})
        self.assertEqual(self.a.post(reverse('chatbot_api'),{'message':''}).status_code,429)
        self.assertEqual(self.b.post(reverse('chatbot_api'),{'message':''}).status_code,400)
        cache.clear()
        for _ in range(6): self.a.post(reverse('cargar_texto_diario'),{})
        self.assertContains(self.a.post(reverse('cargar_texto_diario'),{}),'Espera',status_code=429)
        self.assertEqual(self.a.post(reverse('cargar_texto_diario'),{},HTTP_ACCEPT='application/json').status_code,429)
        self.assertEqual(self.diario(self.b),[])

    def test_sesion_malformada_rutas_antiguas_y_admin_no_adoptan_espacios(self):
        self.sembrar(self.a);workspace=self.a.session['workspace_id']
        for nombre in ('login','registro','logout'):
            self.assertRedirects(self.a.get(reverse(nombre)),reverse('index'))
            self.assertEqual(self.a.session['workspace_id'],workspace)
        sesion=self.b.session;sesion['workspace_id']='uuid-invalido';sesion.save()
        self.assertEqual(self.b.get(reverse('index')).status_code,200)
        self.assertEqual(self.diario(self.b),[])
        user=get_user_model().objects.create_superuser('admin',password='prueba')
        self.a.force_login(user)
        self.assertEqual(self.a.get('/admin/core/asientocontable/').status_code,200)
        self.assertEqual(self.a.session['workspace_id'],workspace)
        self.assertEqual(self.b.get('/admin/core/asientocontable/').status_code,302)
        self.assertEqual(len(self.diario(self.a)),7)
        self.assertEqual(self.a.post('/admin/logout/').status_code,200)
        self.assertEqual(self.a.session['workspace_id'],workspace)
        self.assertNotIn('_auth_user_id',self.a.session)
        self.assertEqual(len(self.diario(self.a)),7)
        self.assertIsNone(actual.get())

    def test_managers_sin_contexto_cerrados_y_via_administrativa_explicita(self):
        self.sembrar(self.a)
        modelos=(CuentaContable,AsientoContable,Movimiento,RespaldoCaso,FinancialRatioPeriod)
        self.assertIsNone(actual.get())
        for modelo in modelos:
            self.assertEqual(modelo.objects.count(),0)
            self.assertEqual(modelo._base_manager.count(),0)
            self.assertEqual(modelo.objects.all().delete()[0],0)
        with self.assertRaises(PermissionDenied):CuentaContable.objects.create(codigo='99',nombre='Fuera de ámbito',tipo='gasto')
        with self.assertRaises(PermissionDenied):CuentaContable.objects.bulk_create([])
        with acceso_administrativo():
            self.assertEqual(AsientoContable.objects.count(),7)
            self.assertGreater(Movimiento.objects.count(),0)
        self.assertEqual(AsientoContable.objects.count(),0)
        self.assertEqual(len(self.diario(self.a)),7)

    def test_respaldo_mas_de_cien_asientos_y_catalogo_sin_movimientos(self):
        self.sembrar(self.a)
        token=actual.set(self.a.session['workspace_id'])
        try:
            CuentaContable.objects.create(codigo='1041',nombre='Banco sin movimientos',tipo='activo')
            original=AsientoContable.objects.first()
            original.fecha_cierre_ejercicio='2025-10-31'
            original.fuente_importacion='Texto original'
            original.observaciones_importacion='Observación original'
            original.save()
        finally:actual.reset(token)
        contenido=self.respaldo(self.a)
        contenido['asientos']=[deepcopy(contenido['asientos'][0]) for _ in range(101)]
        self.assertContains(self.subir(self.b,contenido),'Respaldo importado')
        self.assertEqual(self.respaldo(self.b),contenido)

    def test_comandos_exigen_destino_y_no_tocan_otros_espacios(self):
        self.sembrar(self.a)
        with self.assertRaises(CommandError):call_command('cargar_prueba',workspace='invalido',stdout=StringIO())
        with acceso_administrativo():
            historica=CuentaContable.objects.create(codigo='101',nombre='Caja histórica',tipo='activo')
        destino=self.b.session['workspace_id']
        call_command('asignar_historico',workspace=destino,stdout=StringIO())
        self.assertEqual(self.respaldo(self.b)['cuentas'],[])
        call_command('asignar_historico',workspace=destino,confirmar=True,stdout=StringIO())
        self.assertEqual(self.respaldo(self.b)['cuentas'][0]['nombre'],'Caja histórica')
        self.assertEqual(len(self.diario(self.a)),7)
        call_command('cargar_prueba',workspace=destino,stdout=StringIO())
        self.assertEqual(len(self.diario(self.a)),7)
        self.assertTrue(self.b.get(reverse('respaldos')).context['respaldos'])
        with self.assertRaises(CommandError):call_command('asignar_historico',workspace=destino,confirmar=True,stdout=StringIO())

    def test_qr_solo_abre_camara_y_explica_como_mover_el_caso(self):
        self.sembrar(self.a)
        pantalla=self.a.get(reverse('cargar_imagen_diario'))
        self.assertContains(pantalla,'no se envían a esta computadora ni se vinculan los espacios')
        self.assertContains(pantalla,'descarga su respaldo JSON')
        self.assertContains(pantalla,'id="qrcode-container"')
        self.assertNotContains(pantalla,'Continuar desde el celular')
        self.assertNotContains(pantalla,self.a.session['workspace_id'])
        self.assertIn(reverse('respaldos'),Elementos(pantalla.content.decode()).links)
        # El URL que genera el QR solo contiene la ruta y camara=1.
        celular=self.b.get(reverse('cargar_imagen_diario')+'?camara=1')
        self.assertEqual(celular.status_code,200)
        self.assertEqual(self.diario(self.b),[])
        self.assertEqual(len(self.diario(self.a)),7)
        self.assertNotEqual(self.a.session['workspace_id'],self.b.session['workspace_id'])

    def test_descripcion_obligatoria_en_alta_y_edicion(self):
        self.sembrar(self.a,novatech()[:1])
        for ruta,identificador in [('registrar_asiento','id_descripcion'),('libro_diario','edit_descripcion')]:
            pagina=self.a.get(reverse(ruta))
            self.assertContains(pagina,'Descripción (obligatoria)')
            campo=next(c for c in Elementos(pagina.content.decode()).inputs if c.get('id')==identificador)
            self.assertIn('required',campo)
            self.assertEqual(campo['maxlength'],'2000')
        cuentas={c.codigo:c.pk for c in self.a.get(reverse('registrar_asiento')).context['cuentas']}
        datos={'fecha':'2025-10-02','descripcion':'','num_movimientos':'2',
               'cuenta_0':cuentas['101'],'cuenta_1':cuentas['50'],'tipo_0':'debe','tipo_1':'haber',
               'monto_0':'100','monto_1':'100'}
        original=self.respaldo(self.a)
        pk=self.diario(self.a)[0].pk
        for descripcion in ('','   ','x'*2001):
            entrada={**datos,'descripcion':descripcion}
            self.assertContains(self.a.post(reverse('registrar_asiento'),entrada),'Revise la descripción')
            self.assertContains(self.a.post(reverse('editar_asiento',args=[pk]),entrada,follow=True),'Revise la descripción')
            self.assertEqual(self.respaldo(self.a),original)
        self.assertRedirects(self.a.post(reverse('registrar_asiento'),{**datos,'descripcion':'Nuevo aporte'}),reverse('libro_diario'))
        self.assertEqual(len(self.diario(self.a)),2)
        self.assertEqual(self.diario(self.b),[])

    def preparar_historial(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        self.sembrar(self.a,novatech()[:1])
        contenido=self.respaldo(self.a)
        token=actual.set(self.a.session['workspace_id'])
        try:
            filas=RespaldoCaso.objects.bulk_create([
                RespaldoCaso(datos=contenido['asientos'],catalogo=contenido['cuentas']) for _ in range(55)])
            inicio=datetime(2026,10,1,12,tzinfo=ZoneInfo('America/Lima'))
            for indice,fila in enumerate(filas):
                RespaldoCaso.objects.filter(pk=fila.pk).update(created_at=inicio+timedelta(days=indice//20))
            # Límites exactos: UTC 05:00 equivale a las 00:00 de Lima.
            RespaldoCaso.objects.filter(pk=filas[20].pk).update(created_at=inicio.replace(day=2,hour=0))
            RespaldoCaso.objects.filter(pk=filas[39].pk).update(created_at=inicio.replace(day=2,hour=23,minute=59,second=59))
        finally:actual.reset(token)
        token=actual.set(self.b.session['workspace_id'])
        try:
            ajeno=RespaldoCaso.objects.create(datos=contenido['asientos'],catalogo=contenido['cuentas'])
            RespaldoCaso.objects.filter(pk=ajeno.pk).update(created_at=inicio.replace(day=2))
        finally:actual.reset(token)
        return filas

    def test_paginacion_recupera_respaldos_anteriores_a_los_cincuenta(self):
        filas=self.preparar_historial()
        vistos=[]
        for numero,cuantos in ((1,20),(2,20),(3,15)):
            pagina=self.a.get(reverse('respaldos'),{'pagina':numero})
            self.assertEqual(pagina.context['pagina'].paginator.count,55)
            self.assertEqual(pagina.context['pagina'].number,numero)
            self.assertEqual(len(pagina.context['respaldos']),cuantos)
            vistos.extend(r.pk for r in pagina.context['respaldos'])
            self.assertContains(pagina,f'Página {numero} de 3')
        self.assertEqual(vistos,[r.pk for r in reversed(filas)])
        mas_antiguo=filas[0]
        self.assertEqual(self.a.get(reverse('descargar_respaldo',args=[mas_antiguo.pk])).status_code,200)
        self.assertRedirects(self.a.post(reverse('restaurar_respaldo',args=[mas_antiguo.pk])),reverse('respaldos'))
        self.assertEqual(len(self.diario(self.a)),1)
        self.assertEqual(self.b.get(reverse('descargar_respaldo',args=[mas_antiguo.pk])).status_code,404)
        self.assertEqual(self.b.post(reverse('restaurar_respaldo',args=[mas_antiguo.pk])).status_code,404)
        self.assertEqual(self.b.get(reverse('respaldos')).context['pagina'].paginator.count,1)

    def test_busqueda_fechas_inclusivas_lima_conserva_filtros_y_aislamiento(self):
        filas=self.preparar_historial()
        url=reverse('respaldos')
        r=self.a.get(url,{'desde':'2026-10-02','hasta':'2026-10-02'})
        self.assertEqual({r.pk for r in r.context['respaldos']},{r.pk for r in filas[20:40]})
        self.assertEqual(r.context['pagina'].paginator.count,20)
        desde=self.a.get(url,{'desde':'2026-10-02'})
        self.assertEqual(desde.context['pagina'].paginator.count,35)
        hasta=self.a.get(url,{'hasta':'2026-10-01'})
        self.assertEqual(hasta.context['pagina'].paginator.count,20)
        r=self.a.get(url,{'desde':'2026-10-01','hasta':'2026-10-03'})
        link=next(link for link in Elementos(r.content.decode()).links if 'pagina=2' in link)
        self.assertIn('desde=2026-10-01',link);self.assertIn('hasta=2026-10-03',link)
        siguiente=self.a.get(url+link)
        self.assertEqual(siguiente.context['pagina'].number,2)
        self.assertEqual(siguiente.context['pagina'].paginator.count,55)
        self.assertContains(siguiente,'value="2026-10-01"')
        self.assertEqual(self.b.get(url,{'desde':'2026-10-01','hasta':'2026-10-03'}).context['pagina'].paginator.count,1)
        # Una fecha de operación no se usa como fecha de guardado del respaldo.
        self.assertEqual(self.a.get(url,{'desde':'2025-10-01','hasta':'2025-10-31'}).context['pagina'].paginator.count,0)

    def test_busqueda_invalida_vacia_y_paginas_fuera_de_rango(self):
        self.preparar_historial()
        for filtro in ({'desde':'2026-02-30'},{'hasta':'<script>'},{'desde':'2026-10-03','hasta':'2026-10-01'}):
            with self.subTest(filtro=filtro):
                r=self.a.get(reverse('respaldos'),filtro)
                self.assertEqual(r.status_code,200)
                self.assertFalse(r.context['formulario_busqueda'].is_valid())
                self.assertEqual(r.context['pagina'].paginator.count,0)
                if filtro.get('hasta')=='<script>': self.assertContains(r,'&lt;script&gt;')
        for valor in ('abc','0','-1','9999999999999999999999999999999'):
            r=self.a.get(reverse('respaldos'),{'pagina':valor})
            self.assertEqual(r.status_code,200)
            self.assertLessEqual(r.context['pagina'].number,3)
            self.assertEqual(r.context['pagina'].paginator.count,55)
        vacia=self.a.get(reverse('respaldos'),{'desde':'2027-01-01'})
        self.assertContains(vacia,'No hay respaldos que coincidan')
        self.assertEqual(vacia.context['pagina'].paginator.count,0)
