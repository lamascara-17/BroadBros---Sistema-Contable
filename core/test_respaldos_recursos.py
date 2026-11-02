import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.db import transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .importacion_general import normalizar_borrador
from .models import Workspace, CuentaContable, AsientoContable, RespaldoCaso
from .respaldos import codificar_respaldo, MAX_RESPALDO_BYTES, restaurar, serializar_caso, validar_respaldo
from .test_estados_financieros import novatech
from .test_ciclo_contable import imagen
from .views import guardar_importacion
from .workspaces import actual, acceso_administrativo


def consumir(respuesta):
    if respuesta.streaming:
        contenido = b''.join(respuesta.streaming_content)
        # El cliente Django cierra la respuesta al agotar streaming_content.
        # Cerrar dos veces dispara request_finished dentro del atomic del TestCase.
        from django.http import HttpResponse
        copia = HttpResponse(contenido, content_type='application/json')
        copia.json = lambda: json.loads(contenido)
        return copia
    return respuesta


class Visitantes:
    def setUp(self):
        super().setUp(); cache.clear()
        self.a,self.b=Client(),Client()
        for cliente in (self.a,self.b):cliente.get(reverse('index'))

    def sembrar(self,cliente,datos=None):
        token=actual.set(cliente.session['workspace_id'])
        try:guardar_importacion(datos or novatech())
        finally:actual.reset(token)

    def exportar(self,cliente):
        return consumir(cliente.get(reverse('descargar_actual')))

    def subir(self,cliente,contenido):
        return cliente.post(reverse('importar_respaldo'),{'respaldo':SimpleUploadedFile('caso.json',contenido,content_type='application/json')})


def limite_admitido():
    cuentas=[{'codigo':str(10000000000000000000+i),'nombre':f'{i:04}'+('n'*196),'tipo':'activo','subcategoria':'activo_no_corriente'} for i in range(1000)]
    asientos=[]
    for i in range(1000):
        lineas=[]
        for j in range(40):
            cuenta=cuentas[(i*40+j)%1000]
            lineas.append({'codigo':cuenta['codigo'],'nombre':cuenta['nombre'],'tipo_cuenta':cuenta['tipo'],
                'subcategoria':cuenta['subcategoria'],'tipo_movimiento':'debe' if j<20 else 'haber','monto':'9999999999.99'})
        asientos.append({'fecha':'2025-01-01','descripcion':'D'*2000,'clase':'operacion','flujo_efectivo':'pendiente',
            'fecha_cierre':'2025-12-31','fuente':'f'*20000,'observaciones':'o'*10000,'movimientos':lineas})
    return {'formato':'BROADBROS','version':1,'asientos':asientos,'cuentas':cuentas}


@override_settings(WORKSPACE_ISOLATION=True)
class CompatibilidadRespaldosTests(Visitantes,TestCase):
    def test_roundtrip_actual_e_historico_superiores_a_2mb_en_limites_estructurales(self):
        contenido=limite_admitido()
        token=actual.set(self.a.session['workspace_id'])
        try:
            respaldo=RespaldoCaso.objects.create(datos=contenido['asientos'],catalogo=contenido['cuentas'])
            restaurar(respaldo)
        finally:actual.reset(token)
        historico=consumir(self.a.get(reverse('descargar_respaldo',args=[respaldo.pk])))
        self.assertEqual(historico.status_code,200)
        self.assertGreater(len(historico.content),2*1024*1024)
        self.assertLess(len(historico.content),MAX_RESPALDO_BYTES)
        self.assertEqual(historico.json(),contenido)
        esperado=hashlib.sha256(historico.content).hexdigest()
        actual_exportado=self.exportar(self.a)
        self.assertEqual(hashlib.sha256(actual_exportado.content).hexdigest(),esperado)
        del actual_exportado
        self.sembrar(self.b,novatech()[:1])
        self.assertEqual(self.subir(self.b,historico.content).status_code,302)
        del historico
        recuperado=self.exportar(self.b)
        self.assertEqual(recuperado.status_code,200)
        self.assertEqual(hashlib.sha256(recuperado.content).hexdigest(),esperado)
        token=actual.set(self.b.session['workspace_id'])
        try:
            self.assertEqual(AsientoContable.objects.count(),1000)
            self.assertEqual(CuentaContable.objects.count(),1000)
            self.assertTrue(any(len(r.datos)==1 for r in RespaldoCaso.objects.all()))
        finally:actual.reset(token)
        self.assertEqual(self.b.get(reverse('descargar_respaldo',args=[respaldo.pk])).status_code,404)

    def test_limite_bytes_compartido_exactamente_acepta_y_exceso_rechaza_sin_perder_caso(self):
        self.sembrar(self.a,novatech()[:1])
        archivo=self.exportar(self.a).content
        with patch('core.respaldos.MAX_RESPALDO_BYTES',len(archivo)):
            self.assertEqual(self.exportar(self.a).status_code,200)
            self.assertEqual(self.subir(self.b,archivo).status_code,302)
        antes=self.exportar(self.b).content
        with patch('core.respaldos.MAX_RESPALDO_BYTES',len(archivo)-1):
            self.assertEqual(self.exportar(self.a).status_code,302)
            r=self.subir(self.b,archivo)
            self.assertEqual(r.status_code,302)
        self.assertEqual(self.exportar(self.b).content,antes)

    def test_cota_bytes_cubre_unicode_y_escapado_en_todos_los_campos_admitidos(self):
        # Se mide un asiento extremo y se extrapola sin reservar 256 MB en RAM.
        contenido=limite_admitido()
        asiento=deepcopy(contenido['asientos'][0])
        asiento.update(descripcion='\x00'*2000,fuente='\x00'*20000,observaciones='\x00'*10000)
        for m in asiento['movimientos']:m['nombre']='\x00'*200
        catalogo=[{**c,'nombre':'\x00'*200} for c in contenido['cuentas']]
        longitud=lambda objeto:len(json.dumps(objeto,ensure_ascii=False,separators=(',',':')).encode())
        cota=longitud(asiento)*1000+longitud(catalogo)+10000
        self.assertLess(cota,MAX_RESPALDO_BYTES)
        # El caso extremo estructural también se valida sin truncar sus textos.
        datos,cuentas=validar_respaldo(contenido)
        self.assertEqual(len(datos),1000);self.assertEqual(len(cuentas),1000)
        for clave,tamano in [('descripcion',2000),('fuente',20000),('observaciones',10000)]:
            self.assertEqual(len(datos[-1][clave]),tamano)

    def test_exportacion_no_emite_archivo_que_importador_rechazaria(self):
        self.sembrar(self.a,novatech()[:1])
        base=self.exportar(self.a).json()
        for campo,valor in [('asientos',base['asientos']*1001),('cuentas',base['cuentas']*501)]:
            contenido={**base,campo:valor}
            with self.assertRaises(ValueError):codificar_respaldo(contenido)
        token=actual.set(self.a.session['workspace_id'])
        try:
            respaldo=RespaldoCaso.objects.create(datos=base['asientos']*1001,catalogo=base['cuentas'])
        finally:actual.reset(token)
        r=self.a.get(reverse('descargar_respaldo',args=[respaldo.pk]),follow=True)
        self.assertContains(r,'No se generó un archivo incompleto')
        self.assertEqual(self.exportar(self.a).json(),base)

    def test_cuotas_respaldos_sin_cuenta_no_afectan_otro_visitante(self):
        for _ in range(30):self.assertEqual(self.exportar(self.a).status_code,200)
        self.assertEqual(self.exportar(self.a).status_code,429)
        self.assertEqual(self.exportar(self.b).status_code,200)
        cache.clear()
        for _ in range(12):self.a.post(reverse('importar_respaldo'),{})
        r=self.a.post(reverse('importar_respaldo'),{},HTTP_ACCEPT='application/json')
        self.assertEqual(r.status_code,429);self.assertEqual(r['Retry-After'],'60')
        self.assertEqual(self.b.post(reverse('importar_respaldo'),{}).status_code,302)


@override_settings(WORKSPACE_ISOLATION=True)
class ConversacionCasoTests(Visitantes,TransactionTestCase):
    def preparar_chat(self,cliente):
        sesion=cliente.session
        sesion['nonobot_turnos']=[{'usuario':'Caso anterior','respuesta':'Utilidad antigua'}]
        sesion['nonobot_caso']={'anterior':True};sesion.save()

    def comprobar_limpio(self,cliente):
        self.assertNotIn('nonobot_turnos',cliente.session)
        self.assertNotIn('nonobot_caso',cliente.session)

    def test_restauracion_e_importacion_limpian_solo_la_sesion_destino_tras_commit(self):
        self.sembrar(self.a);self.sembrar(self.a,novatech()[:1]);self.preparar_chat(self.a);self.preparar_chat(self.b)
        respaldo=next(iter(self.a.get(reverse('respaldos')).context['respaldos']))
        self.a.post(reverse('restaurar_respaldo',args=[respaldo.pk]))
        self.comprobar_limpio(self.a)
        self.assertIn('nonobot_turnos',self.b.session)
        archivo=self.exportar(self.a).content
        self.subir(self.b,archivo);self.comprobar_limpio(self.b)
        self.preparar_chat(self.b)
        self.subir(self.b,b'JSON invalido')
        self.assertIn('nonobot_turnos',self.b.session)

    def test_texto_txt_imagen_y_revision_limpian_despues_del_guardado(self):
        from django.core import signing
        borrador=normalizar_borrador({'asientos':novatech(),'pendientes':[],'supuestos':[]})
        texto='\n'.join(f"El {a['fecha'][8:10]}/10/2025: {a['descripcion']}" for a in novatech())
        with patch('core.importacion_general.proponer_caso_general',return_value=borrador):
            for entrada in ({'texto_caso':texto},{'archivo_texto':SimpleUploadedFile('caso.txt',texto.encode())}):
                self.preparar_chat(self.a)
                self.assertEqual(self.a.post(reverse('cargar_texto_diario'),entrada).status_code,302)
                self.comprobar_limpio(self.a)
        self.preparar_chat(self.a)
        with patch('core.ai_diario.extraer_operaciones',return_value={'texto_leido':texto}), patch('core.ciclo_contable.generar_asientos',return_value=novatech()):
            self.assertEqual(self.a.post(reverse('cargar_imagen_diario'),{'foto_camara':imagen()}).status_code,302)
        self.comprobar_limpio(self.a)
        self.preparar_chat(self.a)
        payload={'datos':{'texto_leido':texto},'borrador':borrador,'tasa':None,'limpiar':False}
        token=signing.dumps(payload,salt='revision-contable',compress=True)
        r=self.a.post(reverse('revisar_importacion'),{'revision_token':token,'accion':'guardar','revisado':'on','asientos_json':json.dumps(novatech())})
        self.assertEqual(r.status_code,302);self.comprobar_limpio(self.a)

    def test_fallo_y_rollback_conservan_conversacion_y_caso(self):
        self.sembrar(self.a);self.preparar_chat(self.a)
        antes=self.exportar(self.a).content
        token=actual.set(self.a.session['workspace_id'])
        sesion={'nonobot_turnos':['conversación intacta']}
        try:
            with self.assertRaises(ValueError):
                with transaction.atomic():
                    guardar_importacion(novatech()[:1],session=sesion)
                    self.assertIn('nonobot_turnos',sesion)
                    raise ValueError('Rollback deliberado')
            self.assertIn('nonobot_turnos',sesion)
        finally:actual.reset(token)
        self.assertEqual(self.exportar(self.a).content,antes)
        archivo=antes
        with patch('core.respaldos.Movimiento.objects.bulk_create',side_effect=ValueError('Fallo de escritura')):
            self.subir(self.a,archivo)
        self.assertEqual(self.exportar(self.a).content,antes)
        self.assertIn('nonobot_turnos',self.a.session)
        token=actual.set(self.a.session['workspace_id'])
        try:
            contenido=json.loads(antes)
            respaldo=RespaldoCaso.objects.create(datos=contenido['asientos'],catalogo=contenido['cuentas'])
        finally:actual.reset(token)
        with patch('core.respaldos.Movimiento.objects.bulk_create',side_effect=ValueError('Fallo al restaurar')):
            self.a.post(reverse('restaurar_respaldo',args=[respaldo.pk]))
        self.assertEqual(self.exportar(self.a).content,antes)
        self.assertEqual(self.a.session['nonobot_turnos'],[{'usuario':'Caso anterior','respuesta':'Utilidad antigua'}])
        with patch('core.importacion_general.proponer_caso_general',side_effect=ValueError('Sin cuota')):
            self.a.post(reverse('cargar_texto_diario'),{'texto_caso':'Enunciado válido'})
        self.assertIn('nonobot_turnos',self.a.session)

    def test_historial_antiguo_no_entra_al_prompt_aunque_otro_request_lo_reintroduzca(self):
        from types import SimpleNamespace
        from .contexto_bot import firma_caso
        self.sembrar(self.a)
        token=actual.set(self.a.session['workspace_id'])
        try:vieja_firma=firma_caso();guardar_importacion(novatech()[:1])
        finally:actual.reset(token)
        sesion=self.a.session;sesion['nonobot_turnos']=[{'usuario':'Ejercicio antiguo','respuesta':'NO_INCLUIR_ESTE_SALDO'}];sesion['nonobot_caso']=vieja_firma;sesion.save()
        respuesta=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Explicación nueva'))])
        with override_settings(GROQ_API_KEY='falsa'),patch('core.views.consulta_contable',return_value=True),patch('core.views.Groq') as groq:
            groq.return_value.chat.completions.create.return_value=respuesta
            r=self.a.post(reverse('chatbot_api'),{'message':'Explícame qué es un activo'})
            self.assertEqual(r.status_code,200)
            mensajes=str(groq.return_value.chat.completions.create.call_args.kwargs['messages'])
            self.assertNotIn('NO_INCLUIR_ESTE_SALDO',mensajes)
        self.assertNotEqual(self.a.session['nonobot_caso'],vieja_firma)
        self.assertNotIn('NO_INCLUIR_ESTE_SALDO',str(self.a.session['nonobot_turnos']))


@override_settings(WORKSPACE_ISOLATION=True)
class InventarioAlmacenamientoTests(Visitantes,TestCase):
    def informe(self,**opciones):
        salida=StringIO();call_command('auditar_almacenamiento',stdout=salida,**opciones);return json.loads(salida.getvalue())

    def test_inventario_solo_lectura_excluye_espacios_con_datos_o_sesion_vigente(self):
        viejo=timezone.now()-timedelta(days=200)
        vacio=Workspace.objects.create()
        con_respaldo=Workspace.objects.create()
        Workspace.objects.filter(pk__in=[vacio.pk,con_respaldo.pk,self.a.session['workspace_id']]).update(created_at=viejo)
        token=actual.set(con_respaldo.pk)
        try:RespaldoCaso.objects.create(datos=[],catalogo=[])
        finally:actual.reset(token)
        self.sembrar(self.b)
        informe=self.informe()
        self.assertTrue(informe['solo_lectura'])
        self.assertEqual([r['workspace'] for r in informe['candidatos_vacios_revision']],[str(vacio.pk)])
        self.assertGreater(informe['registros']['RespaldoCaso'],0)
        self.assertEqual(informe['registros']['AsientoContable'],7)
        self.assertEqual(self.informe()['registros'],informe['registros'])
        self.assertTrue(Workspace.objects.filter(pk=vacio.pk).exists())
        self.assertEqual(len(self.a.get(reverse('libro_diario')).context['asientos']),0)
        self.assertEqual(len(self.b.get(reverse('libro_diario')).context['asientos']),7)
        self.assertNotIn('session_key',json.dumps(informe))

    def test_inventario_incompleto_no_declara_abandonados_y_valida_limites(self):
        self.assertFalse(self.informe(max_sesiones=1)['escaneo_sesiones_completo'])
        self.assertEqual(self.informe(max_sesiones=1)['candidatos_vacios_revision'],[])
        with override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies'):
            self.assertEqual(self.informe()['candidatos_vacios_revision'],[])
        for opciones in ({'dias_minimo':179},{'limite':1001},{'max_sesiones':0}):
            with self.assertRaises(CommandError):self.informe(**opciones)
