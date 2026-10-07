from unittest.mock import patch
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from .models import AsientoContable
from .test_importacion_general import propuesta


class ImportacionTextoTests(TestCase):
    def test_texto_literal_se_envia_a_revision_sin_guardar(self):
        texto='El 15/06/2023 se recibe un préstamo de 1000.'
        with patch('core.importacion_general.proponer_caso_general',return_value=propuesta()) as preparar:
            response=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':texto})
        preparar.assert_called_once_with({'texto_leido':texto},None)
        self.assertContains(response,'Revisar ejercicio')
        self.assertEqual(AsientoContable.objects.count(),0)
        self.assertContains(self.client.get(reverse('cargar_texto_diario')),'Importar texto')

    def test_archivos_y_errores_preservan_texto(self):
        texto='Préstamo de 1000.'
        for codificacion in ('utf-8-sig','utf-16'):
            archivo=SimpleUploadedFile('caso.txt',texto.encode(codificacion),content_type='text/plain')
            with patch('core.importacion_general.proponer_caso_general',side_effect=ValueError('Groq alcanzó su límite')) as preparar:
                response=self.client.post(reverse('cargar_texto_diario'),{'archivo_texto':archivo})
            preparar.assert_called_once_with({'texto_leido':texto},None)
            self.assertContains(response,'Groq alcanzó su límite')
            self.assertEqual(response.context['texto_caso'],texto)

    def test_rechaza_entradas_invalidas_sin_llamar_al_servicio(self):
        entradas=[{}, {'texto_caso':'x'*20001}, {'archivo_texto':SimpleUploadedFile('caso.pdf',b'PDF')},
                  {'texto_caso':'texto','archivo_texto':SimpleUploadedFile('caso.txt',b'otro')},
                  {'archivo_texto':SimpleUploadedFile('caso.txt',b'\xff')}]
        with patch('core.importacion_general.proponer_caso_general') as preparar:
            for entrada in entradas:
                response=self.client.post(reverse('cargar_texto_diario'),entrada)
                self.assertEqual(response.status_code,200)
            preparar.assert_not_called()

    def test_impuesto_solicita_tasa_y_conserva_enunciado_firmado(self):
        texto='Compra de equipos por 1000 con IGV incluido.'
        with patch('core.importacion_general.proponer_caso_general',return_value=propuesta()) as preparar:
            response=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':texto})
            preparar.assert_not_called()
            self.assertContains(response,'Tasa de IGV / IVA')
            self.client.post(reverse('cargar_texto_diario'),{'texto_token':response.context['texto_token'],'tasa_impuesto':'18'})
            preparar.assert_called_once_with({'texto_leido':texto},'18')
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_tasa_explicita_y_token_alterado(self):
        with patch('core.importacion_general.proponer_caso_general',return_value=propuesta()) as preparar:
            self.client.post(reverse('cargar_texto_diario'),{'texto_caso':'Compra por 1000 más IGV de 18 %.'})
            self.assertEqual(preparar.call_count,1)
            response=self.client.post(reverse('cargar_texto_diario'),{'texto_token':'falso'})
            self.assertContains(response,'La lectura caducó')
            self.assertEqual(preparar.call_count,1)
