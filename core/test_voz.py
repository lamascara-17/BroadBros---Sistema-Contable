from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from groq import APIStatusError
import httpx


@override_settings(GROQ_API_KEY='clave-de-prueba')
class VozTests(TestCase):
    def audio(self, nombre='consulta.webm', contenido=b'audio-de-prueba'):
        return SimpleUploadedFile(nombre, contenido, content_type='audio/webm')

    def test_transcribe_en_espanol_sin_crear_asientos(self):
        from .models import AsientoContable
        with patch('core.voz.Groq') as groq:
            groq.return_value.audio.transcriptions.create.return_value = SimpleNamespace(text='Explica el asiento de compra.')
            response = self.client.post(reverse('transcribir_voz'), {'audio': self.audio()})
            self.assertEqual(response.json(), {'texto': 'Explica el asiento de compra.'})
            args = groq.return_value.audio.transcriptions.create.call_args.kwargs
            self.assertEqual(args['language'], 'es')
            self.assertEqual(args['model'], 'whisper-large-v3-turbo')
            self.assertEqual(args['file'], ('consulta.webm', b'audio-de-prueba'))
            self.assertEqual(AsientoContable.objects.count(), 0)

    def test_rechaza_audio_invalido_y_get_sin_llamar_a_groq(self):
        with patch('core.voz.Groq') as groq:
            self.assertEqual(self.client.get(reverse('transcribir_voz')).status_code, 405)
            for entrada in ({}, {'audio': self.audio('consulta.exe')}, {'audio': self.audio(contenido=b'')},
                            {'audio': self.audio(contenido=b'x' * (10 * 1024 * 1024 + 1))}):
                self.assertEqual(self.client.post(reverse('transcribir_voz'), entrada).status_code, 400)
            groq.assert_not_called()
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('transcribir_voz'), {'audio': self.audio()}).status_code, 403)

    def test_limite_de_audio_no_expone_errores_del_proveedor(self):
        error = APIStatusError('detalle privado', response=httpx.Response(429, request=httpx.Request('POST', 'https://api.groq.com')), body={'clave': 'privada'})
        with patch('core.voz.Groq') as groq:
            groq.return_value.audio.transcriptions.create.side_effect = error
            response = self.client.post(reverse('transcribir_voz'), {'audio': self.audio()})
        self.assertEqual(response.status_code, 429)
        self.assertIn('límite de audio', response.json()['error'])
        self.assertNotIn('privad', response.content.decode())

    def test_configuracion_ausente_y_voz_vacia(self):
        with override_settings(GROQ_API_KEY=''), patch('core.voz.Groq') as groq:
            self.assertEqual(self.client.post(reverse('transcribir_voz'), {'audio': self.audio()}).status_code, 503)
            groq.assert_not_called()
        with patch('core.voz.Groq') as groq:
            groq.return_value.audio.transcriptions.create.return_value = SimpleNamespace(text='')
            self.assertEqual(self.client.post(reverse('transcribir_voz'), {'audio': self.audio()}).status_code, 422)
