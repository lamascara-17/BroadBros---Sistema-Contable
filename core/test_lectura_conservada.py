import json
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from .ai_diario import extraer_operaciones
from .models import AsientoContable
from .test_servicio_ia import fallo
from .test_ciclo_contable import imagen
from .test_importacion_general import propuesta


def limite_salida():
    error=fallo(429,'rate_limit_exceeded')
    error.body={'error':{'code':'rate_limit_exceeded','message':'Request too large on output tokens per minute (OTPM): Limit 1000, Requested 1469. org_privada'}}
    return error


def respuesta(texto,fin='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=fin,message=SimpleNamespace(content=texto))])


class LecturaConservadaTests(TestCase):
    @override_settings(GROQ_API_KEY='test-key')
    def test_limite_de_salida_conserva_transcripcion_y_reintenta_sin_imagen(self):
        texto='El 15/06/2023 se recibe un préstamo bancario por 1000.'
        with patch('core.ai_diario.Groq') as groq,patch('core.importacion_general.proponer_caso_general',side_effect=[ValueError('Límite de tokens'),propuesta()]) as general:
            vision=groq.return_value.chat.completions.create
            vision.side_effect=[limite_salida(),respuesta(texto)]
            response=self.client.post(reverse('cargar_imagen_diario'),{'imagen_caso':imagen(),'revisar':'on'})
            self.assertContains(response,'Reintentar con la lectura conservada')
            self.assertContains(response,texto)
            self.assertEqual(response.context['pendientes'],[])
            self.assertEqual(vision.call_count,2)
            self.assertEqual(vision.call_args.kwargs['max_completion_tokens'],1000)
            self.assertNotIn('response_format',vision.call_args.kwargs)
            token=response.context['revision_token']
            response=self.client.post(reverse('revisar_importacion'),{'revision_token':token,'accion':'reintentar'})
            self.assertEqual(vision.call_count,2)
            self.assertEqual(general.call_args.args[0]['texto_leido'],texto)
            self.assertEqual(len(response.context['asientos']),1)
        self.assertEqual(AsientoContable.objects.count(),0)

    @override_settings(GROQ_API_KEY='test-key')
    def test_transcripcion_truncada_se_muestra_editable_y_no_genera_asientos(self):
        with patch('core.ai_diario.Groq') as groq,patch('core.importacion_general.proponer_caso_general') as general:
            groq.return_value.chat.completions.create.side_effect=[limite_salida(),respuesta('Aporte 1000. Compra de','length')]
            response=self.client.post(reverse('cargar_imagen_diario'),{'imagen_caso':imagen()})
            self.assertContains(response,'Completar la lectura conservada')
            self.assertNotContains(response,'Reintentar con la lectura conservada')
            general.assert_not_called()
            token=response.context['revision_token']
            for accion in ('reintentar','guardar'):
                response=self.client.post(reverse('revisar_importacion'),{'revision_token':token,'accion':accion,'revisado':'on','asientos_json':json.dumps(propuesta()['asientos'])})
                self.assertEqual(response.status_code,200)
            general.assert_not_called()
        self.assertEqual(AsientoContable.objects.count(),0)

    @override_settings(GROQ_API_KEY='test-key')
    def test_otros_limites_no_reenvian_la_imagen(self):
        for error in (fallo(429),fallo(401),fallo(413)):
            with patch('core.ai_diario.Groq') as groq:
                groq.return_value.chat.completions.create.side_effect=error
                with self.assertRaises(ValueError):extraer_operaciones(imagen())
                self.assertEqual(groq.return_value.chat.completions.create.call_count,1)

    @override_settings(GROQ_API_KEY='test-key')
    def test_error_de_cuota_no_expone_identificador_de_cuenta(self):
        with patch('core.ai_diario.Groq') as groq:
            groq.return_value.chat.completions.create.side_effect=[limite_salida(),fallo(429)]
            with self.assertRaises(ValueError) as error:extraer_operaciones(imagen())
            self.assertNotIn('org_privada',str(error.exception))
