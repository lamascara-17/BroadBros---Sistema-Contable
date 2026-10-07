import os
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.core import signing
import httpx
from .audio_respuesta import datos_audio


class AudioRespuestaTests(TestCase):
    def test_sin_clave_usa_voz_del_dispositivo(self):
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': '', 'NONOBOT_VOICE_ID': ''}):
            self.assertEqual(datos_audio('Hola'), {'audio_personalizado': False})

    def test_audio_solo_con_respuesta_firmada_y_clave_en_servidor(self):
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'clave-privada', 'NONOBOT_VOICE_ID': 'voz123'}):
            datos = datos_audio('Caja aumenta S/ 100.')
            self.assertNotIn('clave-privada', str(datos))
            with patch('core.audio_respuesta.httpx.post') as post:
                post.return_value = httpx.Response(200, content=b'mp3-prueba', headers={'content-type': 'audio/mpeg'}, request=httpx.Request('POST', 'https://api.elevenlabs.io'))
                response = self.client.post(reverse('respuesta_audio'), {'token': datos['audio_token']})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b'mp3-prueba')
            self.assertEqual(response['Cache-Control'], 'no-store')
            self.assertEqual(post.call_args.kwargs['json']['text'], 'Caja aumenta S/ 100.')
            self.assertEqual(post.call_args.kwargs['headers']['xi-api-key'], 'clave-privada')
            self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('respuesta_audio'), {'token': datos['audio_token']}).status_code, 403)

    def test_no_procesa_token_falso_ni_audio_sin_configuracion(self):
        with patch('core.audio_respuesta.httpx.post') as post:
            self.assertEqual(self.client.post(reverse('respuesta_audio'), {'token': 'falso'}).status_code, 400)
            self.assertEqual(self.client.get(reverse('respuesta_audio')).status_code, 405)
            token = signing.dumps({'texto': 'Hola'}, salt='nonobot-audio')
            with patch.dict(os.environ, {'ELEVENLABS_API_KEY': '', 'NONOBOT_VOICE_ID': ''}):
                self.assertEqual(self.client.post(reverse('respuesta_audio'), {'token': token}).status_code, 503)
            post.assert_not_called()

    def test_error_del_proveedor_no_expone_clave(self):
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'clave-privada', 'NONOBOT_VOICE_ID': 'voz123'}):
            token = datos_audio('Hola')['audio_token']
            with patch('core.audio_respuesta.httpx.post', side_effect=RuntimeError('clave-privada')):
                response = self.client.post(reverse('respuesta_audio'), {'token': token})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('clave-privada', response.content.decode())
