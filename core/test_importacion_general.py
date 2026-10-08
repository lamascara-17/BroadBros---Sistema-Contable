"""Lectura general, revisión de pendientes y confirmación antes de escribir."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from django.core import signing
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from .importacion_general import validar_asientos, normalizar_borrador, proponer_caso_general
from .models import AsientoContable, Movimiento
from .reporte_utils import contexto_estados
from .test_ciclo_contable import imagen, caso
from .test_ciclo_documentado import caso_letras


def propuesta():
    return {'asientos':[{'fecha':'2023-06-15','descripcion':'Por el préstamo bancario recibido','fuente':'El banco abona 1000 como préstamo.',
             'movimientos':[{'codigo':'1041','nombre':'Cuentas corrientes operativas','tipo_cuenta':'activo','subcategoria':'','tipo_movimiento':'debe','monto':'1000'},
                            {'codigo':'451','nombre':'Préstamos de instituciones financieras','tipo_cuenta':'pasivo','subcategoria':'','tipo_movimiento':'haber','monto':'1000'}]}],
            'pendientes':['Falta el importe del retiro mencionado en la segunda operación.'],'supuestos':[]}


def datos_generales():
    return {'empresa_nueva':False,'metodo_inventario':None,'fecha_cierre':None,'errores_lectura':[],
            'texto_leido':'El 15 de junio de 2023 se recibe un préstamo bancario por 1000. Después se retira efectivo, sin importe indicado.',
            'operaciones':[{'tipo':'no_soportada','fecha':'2023-06-15','texto':'Se recibe un préstamo bancario por 1000.','monto':1000}]}


class ValidadorGeneralTests(TestCase):
    def test_cuadre_exacto_y_clasificacion_consistente(self):
        self.assertEqual(len(validar_asientos(propuesta()['asientos'])),1)
        cambios=[lambda a:a[0]['movimientos'][0].update(monto='1000.01'),
                 lambda a:a[0].update(fecha=''),
                 lambda a:a[0]['movimientos'][0].update(monto='NaN'),
                 lambda a:a[0]['movimientos'][0].update(tipo_cuenta='pasivo',subcategoria='costo_ventas'),
                 lambda a:a[0]['movimientos'][0].update(codigo='<script>')]
        for cambiar in cambios:
            a=propuesta()['asientos'];cambiar(a)
            with self.assertRaises(ValueError):validar_asientos(a)
        a=propuesta()['asientos'];otro=deepcopy(a[0]);otro['movimientos'][0]['tipo_cuenta']='gasto';a.append(otro)
        with self.assertRaises(ValueError):validar_asientos(a)

    def test_borrador_incompleto_se_puede_corregir_sin_inventar(self):
        p=propuesta();p['asientos'][0]['fecha']=None;p['asientos'][0]['movimientos'][0]['monto']=None
        borrador=normalizar_borrador(p)
        self.assertEqual(borrador['asientos'][0]['fecha'],'')
        self.assertEqual(borrador['asientos'][0]['movimientos'][0]['monto'],'')
        self.assertTrue(borrador['asientos'][0]['error_validacion'])
        self.assertEqual(normalizar_borrador({'asientos':[]})['pendientes'],['No hay información suficiente para proponer asientos. Complete los datos del ejercicio.'])

    @override_settings(GROQ_API_KEY='test-key')
    def test_propuesta_usa_texto_extraido_y_aclaraciones(self):
        from .models import CuentaContable
        CuentaContable.objects.create(codigo='1101', nombre='Caja', tipo='activo')
        with patch('core.importacion_general.Groq') as groq:
            groq.return_value.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(propuesta())))])
            borrador=proponer_caso_general(datos_generales(),'18','El retiro fue de 100.')
            parametros=groq.return_value.chat.completions.create.call_args.kwargs
            self.assertIn('El retiro fue de 100.',parametros['messages'][1]['content'])
            self.assertNotIn('plan_cuentas', json.loads(parametros['messages'][1]['content']))
            self.assertEqual(borrador['pendientes'],propuesta()['pendientes'])
            groq.return_value.chat.completions.create.return_value.choices[0].finish_reason='length'
            with self.assertRaises(ValueError):proponer_caso_general(datos_generales(),'18')

    @override_settings(GROQ_API_KEY='test-key')
    def test_lectura_de_apertura_sin_operaciones_no_se_rechaza(self):
        from .ai_diario import extraer_operaciones
        datos={'operaciones':[],'saldos_apertura':[{'concepto':'capital','monto':1000}],'texto_leido':'Capital 1000 y caja 1000.'}
        with patch('core.ai_diario.Groq') as groq:
            groq.return_value.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(datos)))])
            self.assertEqual(extraer_operaciones(imagen()),datos)


class RevisionGeneralTests(TestCase):
    def cargar_general(self):
        with patch('core.ai_diario.extraer_operaciones',return_value=datos_generales()),patch('core.importacion_general.proponer_caso_general',return_value=propuesta()):
            response=self.client.post(reverse('cargar_imagen_diario'),{'imagen_caso':imagen(),'limpiar':'on'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Revisar ejercicio')
        return response.context['revision_token']

    def guardar(self,token,**cambios):
        post={'revision_token':token,'accion':'guardar','revisado':'on','aceptar_parcial':'on','asientos_json':json.dumps(propuesta()['asientos'])}
        post.update(cambios)
        return self.client.post(reverse('revisar_importacion'),post)

    def test_operacion_general_no_se_guarda_sin_confirmacion(self):
        token=self.cargar_general()
        self.assertEqual(AsientoContable.objects.count(),0)
        self.assertEqual(self.guardar(token,revisado='').status_code,200)
        self.assertEqual(self.guardar(token,aceptar_parcial='').status_code,200)
        self.assertEqual(AsientoContable.objects.count(),0)
        self.assertRedirects(self.guardar(token),reverse('libro_diario'))
        self.assertEqual(AsientoContable.objects.count(),1)
        self.assertEqual(Movimiento.objects.count(),2)
        self.assertIn('Falta el importe',AsientoContable.objects.get().observaciones_importacion)
        self.assertIn('Registro parcial',contexto_estados()['nota_resultado'])
        self.assertContains(self.client.get(reverse('balance_general')),'Registro parcial')

    def test_caso_completo_tambien_ofrece_revision(self):
        with patch('core.ai_diario.extraer_operaciones',return_value=caso()):
            response=self.client.post(reverse('cargar_imagen_diario'),{'imagen_caso':imagen(),'limpiar':'on','revisar':'on'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['asientos']),14)
        self.assertEqual(AsientoContable.objects.count(),0)
        payload=signing.loads(response.context['revision_token'],salt='revision-contable')
        post={'revision_token':response.context['revision_token'],'revisado':'on','asientos_json':json.dumps(payload['borrador']['asientos'])}
        self.assertRedirects(self.client.post(reverse('revisar_importacion'),post),reverse('libro_diario'))
        self.assertEqual(AsientoContable.objects.count(),14)

    def test_caso_foto_letras_revisado_guarda_siete_asientos(self):
        with patch('core.ai_diario.extraer_operaciones',return_value=caso_letras()):
            response=self.client.post(reverse('cargar_imagen_diario'),{'imagen_caso':imagen(),'limpiar':'on','revisar':'on','tasa_impuesto':'18'})
        payload=signing.loads(response.context['revision_token'],salt='revision-contable')
        self.assertEqual(len(payload['borrador']['asientos']),7)
        self.assertRedirects(self.guardar(response.context['revision_token'],asientos_json=json.dumps(payload['borrador']['asientos'])),reverse('libro_diario'))
        self.assertEqual(contexto_estados()['total_activos'],7200000)

    def test_guardado_invalido_conserva_correcciones_y_datos_anteriores(self):
        previo=AsientoContable.objects.create(fecha='2020-01-01',descripcion='Registro previo')
        token=self.cargar_general();asientos=propuesta()['asientos'];asientos[0]['movimientos'][0]['monto']='1000.01'
        response=self.guardar(token,asientos_json=json.dumps(asientos))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'1000.01')
        self.assertContains(response,'no cuadra')
        self.assertEqual(list(AsientoContable.objects.values_list('id',flat=True)),[previo.id])
        self.assertRedirects(self.guardar(token+'alterado'),reverse('cargar_imagen_diario'))

    def test_completar_datos_sin_volver_a_subir_la_imagen(self):
        token=self.cargar_general()
        nuevo=propuesta();nuevo['pendientes']=[]
        with patch('core.importacion_general.proponer_caso_general',return_value=nuevo) as proponer:
            response=self.client.post(reverse('revisar_importacion'),{'revision_token':token,'accion':'completar','datos_adicionales':'El retiro fue de 100.'})
        self.assertRedirects(response,reverse('libro_diario'))
        self.assertEqual(proponer.call_args.args[2],'El retiro fue de 100.')
        self.assertEqual(AsientoContable.objects.count(),1)

    def test_excluir_asientos_exige_guardado_parcial(self):
        p=propuesta();p['pendientes']=[];p['asientos'].append(deepcopy(p['asientos'][0]))
        payload={'datos':datos_generales(),'tasa':'18','limpiar':False,'borrador':p}
        token=signing.dumps(payload,salt='revision-contable',compress=True)
        response=self.guardar(token,aceptar_parcial='')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Confirme el guardado parcial')
        self.assertEqual(AsientoContable.objects.count(),0)
