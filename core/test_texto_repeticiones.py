import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

from .test_support import AdministrativeTestCase as TestCase
from .test_estados_financieros import novatech
from .models import AsientoContable
from .importacion_general import normalizar_borrador, proponer_caso_general, serializar_asientos, PropuestaInvalida
from .notas_importacion import normalizar_notas, notas_repetitivas


def respuesta(datos):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(datos)))])


class TextoSinBuclesTests(TestCase):
    def test_reproduce_parrafo_de_la_captura_y_conserva_notas_diferentes(self):
        frase='No se indica si se requiere registrar la compra de activos de uso propio.'
        notas=[(' '+frase)*12,'Falta importe de S/ 100.','Falta importe de S/ 200.']
        self.assertTrue(notas_repetitivas({'pendientes':notas}))
        self.assertEqual(normalizar_notas(notas),[frase,'Falta importe de S/ 100.','Falta importe de S/ 200.'])
        self.assertEqual(normalizar_notas([' Falta la fecha.','falta  la fecha!']),['Falta la fecha.'])

    @override_settings(GROQ_API_KEY='solo-prueba')
    def test_salida_repetitiva_activa_un_rescate_con_el_texto_integro(self):
        texto='El 01/10/2025 se aporta S/ 30,000 al contado.'
        malas={'asientos':serializar_asientos(novatech()[:1]),'pendientes':['Falta confirmar una compra no indicada. '*10],'supuestos':[]}
        buenas={'asientos':serializar_asientos(novatech()[:1]),'pendientes':[],'supuestos':[]}
        with patch('core.importacion_general.Groq'), patch('core.importacion_general.solicitar_json',side_effect=[respuesta(malas),respuesta({'bloques':[texto]}),respuesta(buenas)]) as solicitar:
            resultado=proponer_caso_general({'texto_leido':texto},None)
        self.assertEqual(solicitar.call_count,3)
        self.assertEqual(len(resultado['asientos']),1)
        self.assertEqual(resultado['pendientes'],[])
        self.assertTrue(resultado['lectura_reorganizada'])
        self.assertEqual(json.loads(solicitar.call_args.kwargs['messages'][1]['content'])['ejercicio']['texto_leido'],texto)
        self.assertEqual(AsientoContable.objects.count(),0)

    @override_settings(GROQ_API_KEY='solo-prueba')
    def test_rescate_caido_conserva_propuesta_y_exige_revision(self):
        malas={'asientos':serializar_asientos(novatech()[:1]),'pendientes':['Falta revisar la compra. '*10],'supuestos':[]}
        with patch('core.importacion_general.Groq'), patch('core.importacion_general.solicitar_json',side_effect=[respuesta(malas),ValueError('Servicio temporalmente no disponible')]):
            resultado=proponer_caso_general({'texto_leido':'El 01/10/2025 aporta 30000.'},None)
        self.assertEqual(len(resultado['asientos']),1)
        self.assertEqual(resultado['pendientes'],['Falta revisar la compra.'])
        self.assertTrue(any('repetitivas' in nota for nota in resultado['supuestos']))
        self.assertEqual(AsientoContable.objects.count(),0)

    @override_settings(GROQ_API_KEY='solo-prueba')
    def test_sin_asientos_y_con_bucles_no_inventa_operaciones(self):
        malas={'asientos':[],'pendientes':['Falta revisar el caso. '*10],'supuestos':[]}
        with patch('core.importacion_general.Groq'),patch('core.importacion_general.solicitar_json',side_effect=[respuesta(malas),ValueError('Servicio caído')]):
            with self.assertRaisesMessage(PropuestaInvalida,'repetitivas'):
                proponer_caso_general({'texto_leido':'Ejercicio sin importes suficientes.'},None)

    def test_revision_voluntaria_no_guarda_aunque_el_caso_este_completo(self):
        propuesta=normalizar_borrador({'asientos':novatech(),'pendientes':[],'supuestos':[]})
        with patch('core.importacion_general.proponer_caso_general',return_value=propuesta):
            response=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':'Caso NovaTech completo','revisar':'on'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['asientos']),7)
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_tasa_de_impuesto_conserva_la_eleccion_de_revision(self):
        propuesta=normalizar_borrador({'asientos':novatech(),'pendientes':[],'supuestos':[]})
        with patch('core.importacion_general.proponer_caso_general',return_value=propuesta):
            initial=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':'Caso con IGV incluido.','revisar':'on'})
            response=self.client.post(reverse('cargar_texto_diario'),{'texto_token':initial.context['texto_token'],'tasa_impuesto':'18'})
        self.assertContains(response,'Revisar ejercicio')
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_los_pendientes_se_ven_una_vez_y_el_resto_se_puede_desplegar(self):
        notas=[f'Falta el dato concreto número {i}.' for i in range(1,9)]
        propuesta=normalizar_borrador({'asientos':novatech(),'pendientes':notas+notas,'supuestos':['Convención documentada.']})
        with patch('core.importacion_general.proponer_caso_general',return_value=propuesta):
            response=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':'Caso de prueba'})
        self.assertEqual(len(response.context['pendientes']),8)
        self.assertContains(response,'Ver los demás datos pendientes')
        for nota in notas:self.assertEqual(response.content.decode().count(nota),1)
        self.assertEqual(AsientoContable.objects.count(),0)
