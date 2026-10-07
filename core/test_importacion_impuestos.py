from unittest.mock import patch
from django.core import signing
from django.test import TestCase
from django.urls import reverse
from .test_ciclo_contable import imagen, caso
from .test_ciclo_documentado import caso_letras
from .models import AsientoContable


class VentanaImpuestoTests(TestCase):
    def test_pantalla_solo_imagen_y_camara(self):
        response = self.client.get(reverse('cargar_imagen_diario'))
        self.assertContains(response, 'Subir imagen')
        self.assertContains(response, 'capture="environment"')
        self.assertNotContains(response, 'name="tasa_impuesto"')
        self.assertNotContains(response, 'qrcode')
        self.assertNotContains(response, 'name="limpiar"')

    def test_tasa_pendiente_y_continuacion_sin_repetir_lectura(self):
        with patch('core.ai_diario.extraer_operaciones', return_value=caso_letras()) as lectura:
            response = self.client.post(reverse('cargar_imagen_diario'), {'imagen_caso': imagen(), 'revisar': 'on'})
            self.assertContains(response, '<dialog')
            token = response.context['lectura_token']
            self.assertEqual(AsientoContable.objects.count(), 0)
            response = self.client.post(reverse('cargar_imagen_diario'), {'lectura_token': token, 'tasa_impuesto': '18'})
            self.assertContains(response, 'Revisar ejercicio')
            self.assertEqual(len(response.context['asientos']), 7)
            self.assertEqual(lectura.call_count, 1)
            self.assertEqual(AsientoContable.objects.count(), 0)

    def test_tasa_explicita_y_caso_sin_impuesto_no_abren_ventana(self):
        datos = caso_letras()
        for op in datos['operaciones'][:2]: op['tasa_impuesto'] = '18'
        for ejercicio in [datos, caso()]:
            with patch('core.ai_diario.extraer_operaciones', return_value=ejercicio):
                response = self.client.post(reverse('cargar_imagen_diario'), {'foto_camara': imagen(), 'revisar': 'on'})
                self.assertContains(response, 'Revisar ejercicio')
                self.assertNotContains(response, '<dialog')

    def test_tasa_invalida_conserva_lectura_y_token_alterado_no_guarda(self):
        token = signing.dumps({'datos': caso_letras(), 'limpiar': False, 'revisar': True}, salt='lectura-impuesto')
        with patch('core.ai_diario.extraer_operaciones') as lectura:
            for valor in ['-1', '101', 'abc']:
                response = self.client.post(reverse('cargar_imagen_diario'), {'lectura_token': token, 'tasa_impuesto': valor})
                self.assertContains(response, '<dialog')
                self.assertTrue(response.context['error_tasa'])
                self.assertEqual(response.context['lectura_token'], token)
            response = self.client.post(reverse('cargar_imagen_diario'), {'lectura_token': token+'x', 'tasa_impuesto': '18'}, follow=True)
            self.assertContains(response, 'La lectura caducó o no es válida')
            lectura.assert_not_called()
        self.assertEqual(AsientoContable.objects.count(), 0)
