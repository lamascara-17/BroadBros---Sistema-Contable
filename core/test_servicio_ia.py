import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
import httpx
from groq import APIStatusError, APIConnectionError, APITimeoutError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from .servicio_ia import solicitar_json, leer_json, presupuesto_ia
from .test_ciclo_contable import imagen


def fallo(estado, codigo='invalid_api_key'):
    respuesta = httpx.Response(estado, request=httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions'))
    return APIStatusError('contenido confidencial', response=respuesta, body={'error': {'code': codigo}})


class ServicioIATests(SimpleTestCase):
    def test_esquema_estricto_no_se_descarta_ante_un_error(self):
        client = Mock()
        client.chat.completions.create.side_effect = fallo(400, 'json_validate_failed')
        with self.assertRaises(ValueError):
            solicitar_json(client, model='text', response_format={'type':'json_schema'})
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_presupuesto_acota_llamadas_y_se_restauran_los_plazos(self):
        client = Mock()
        with patch('core.servicio_ia.monotonic', side_effect=[100, 160, 176]):
            with presupuesto_ia(75):
                solicitar_json(client, model='text')
                self.assertEqual(client.chat.completions.create.call_args.kwargs['timeout'], 15)
                with self.assertRaisesMessage(ValueError, 'tiempo límite'):
                    solicitar_json(client, model='text')
        self.assertEqual(client.chat.completions.create.call_count, 1)
        solicitar_json(client, model='text')
        self.assertEqual(client.chat.completions.create.call_args.kwargs['timeout'], 25)

    def test_errores_concretos_sin_exponer_respuesta(self):
        for estado, texto in [(401, 'clave'), (403, 'permiso'), (404, 'modelo'), (429, 'límite'), (500, 'temporalmente')]:
            with self.subTest(estado=estado):
                client = Mock()
                client.chat.completions.create.side_effect = fallo(estado)
                with self.assertRaises(ValueError) as error:
                    solicitar_json(client, model='vision', response_format={'type': 'json_object'})
                self.assertIn(texto, str(error.exception))
                self.assertNotIn('confidencial', str(error.exception))
                self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_reintento_solo_por_fallo_del_modo_json(self):
        client = Mock()
        respuesta = SimpleNamespace(choices=[])
        client.chat.completions.create.side_effect = [fallo(400, 'json_validate_failed'), respuesta]
        self.assertIs(solicitar_json(client, model='vision', messages=[], response_format={'type': 'json_object'}), respuesta)
        self.assertNotIn('response_format', client.chat.completions.create.call_args.kwargs)
        self.assertEqual(client.chat.completions.create.call_count, 2)
        client.chat.completions.create.side_effect = fallo(400, 'request_too_large')
        with self.assertRaises(ValueError): solicitar_json(client, model='vision')

    def test_solicitud_demasiado_grande_no_sugiere_esperar(self):
        client = Mock()
        error = fallo(429, 'rate_limit_exceeded')
        error.body={'error':{'code':'rate_limit_exceeded','message':'Request too large for model on output tokens per minute (OTPM): Limit 1000, Requested 1469. org_privada'}}
        client.chat.completions.create.side_effect=error
        with self.assertRaises(ValueError) as resultado:
            solicitar_json(client,model='vision')
        self.assertIn('Límite: 1000; solicitud: 1469 tokens',str(resultado.exception))
        self.assertIn('Esperar no reduce',str(resultado.exception))
        self.assertNotIn('org_privada',str(resultado.exception))

    def test_conexion_y_timeout(self):
        request = httpx.Request('POST', 'https://api.groq.com')
        for fallo_api in [APIConnectionError(request=request), APITimeoutError(request=request)]:
            client = Mock()
            client.chat.completions.create.side_effect = fallo_api
            with self.assertRaises(ValueError): solicitar_json(client, model='vision')

    def test_json_con_delimitadores_sigue_validandose(self):
        self.assertEqual(leer_json('```json\n{"monto": 1.23}\n```'), {'monto': '1.23'})
        with self.assertRaises(json.JSONDecodeError): leer_json('Texto previo {"monto": 1}')

    @override_settings(GROQ_API_KEY='test-key')
    @patch('core.ai_diario.Groq')
    def test_upload_muestra_limite_en_lugar_del_error_generico(self, groq):
        groq.return_value.chat.completions.create.side_effect = fallo(429)
        respuesta = self.client.post(reverse('cargar_imagen_diario'), {'imagen_caso': imagen(), 'revisar': 'on'}, follow=True)
        self.assertContains(respuesta, 'Groq alcanzó su límite de uso')
        self.assertNotContains(respuesta, 'contenido confidencial')
