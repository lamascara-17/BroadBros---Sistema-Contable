import json
from unittest.mock import patch
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from .models import AsientoContable
from .test_distribuidora import caso_andina
from .test_ciclo_documentado import caso_letras
from .test_importacion_general import datos_generales, propuesta


class ImportacionTextoTests(TestCase):
    def test_texto_y_archivo_usan_revision_sin_vision_ni_guardado_automatico(self):
        dato=caso_andina()
        entradas=[{'texto_caso':dato['texto_leido']},
                  {'archivo_texto':SimpleUploadedFile('caso.txt',dato['texto_leido'].encode('utf-8-sig'))},
                  {'archivo_texto':SimpleUploadedFile('caso.txt',dato['texto_leido'].encode('utf-16'))}]
        for entrada in entradas:
            with patch('core.ai_diario.extraer_operaciones_texto',return_value=dato) as analizar,patch('core.ai_diario.extraer_operaciones') as vision:
                respuesta=self.client.post(reverse('cargar_texto_diario'),entrada)
                self.assertContains(respuesta,'Revisar ejercicio')
                self.assertEqual(len(respuesta.context['asientos']),12)
                self.assertEqual(analizar.call_args.args[0],dato['texto_leido'])
                vision.assert_not_called()
                self.assertEqual(AsientoContable.objects.count(),0)

    def test_archivos_invalidos_no_llegan_al_servicio(self):
        entradas=[{}, {'archivo_texto':SimpleUploadedFile('caso.pdf',b'abc')},
                  {'archivo_texto':SimpleUploadedFile('caso.txt',b'\xff\xff')},
                  {'archivo_texto':SimpleUploadedFile('caso.txt',b'x'*100001)},
                  {'texto_caso':'hola','archivo_texto':SimpleUploadedFile('caso.txt',b'otro')}]
        # Un texto vacío llega al validador de texto; los archivos inválidos no.
        for entrada in entradas[1:]:
            with patch('core.ai_diario.extraer_operaciones_texto') as analizar:
                self.assertEqual(self.client.post(reverse('cargar_texto_diario'),entrada).status_code,200)
                analizar.assert_not_called()
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_impuesto_pregunta_y_continua_sin_nuevo_analisis(self):
        with patch('core.ai_diario.extraer_operaciones_texto',return_value=caso_letras()) as analizar:
            respuesta=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':'Caso con IVA incluido.'})
            self.assertContains(respuesta,'id="tax-dialog"')
            respuesta=self.client.post(reverse('cargar_texto_diario'),{'lectura_token':respuesta.context['lectura_token'],'tasa_impuesto':'18'})
            self.assertContains(respuesta,'Revisar ejercicio')
            self.assertEqual(analizar.call_count,1)

    def test_error_del_servicio_conserva_texto_y_no_lo_presenta_como_dato_faltante(self):
        texto=datos_generales()['texto_leido']
        with patch('core.ai_diario.extraer_operaciones_texto',return_value=datos_generales()),patch('core.importacion_general.proponer_caso_general',side_effect=ValueError('La solicitud excede la cuota.')):
            respuesta=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':texto})
        self.assertEqual(respuesta.context['texto_ejercicio'],texto)
        self.assertEqual(respuesta.context['pendientes'],[])
        self.assertContains(respuesta,'Reintentar con la lectura conservada')
        self.assertContains(respuesta,'La solicitud excede la cuota.')
        with patch('core.importacion_general.proponer_caso_general',return_value=propuesta()),patch('core.ai_diario.extraer_operaciones_texto') as leer:
            respuesta=self.client.post(reverse('revisar_importacion'),{'revision_token':respuesta.context['revision_token'],'accion':'reintentar'})
            leer.assert_not_called()
        self.assertEqual(len(respuesta.context['asientos']),1)
        self.assertEqual(respuesta.context['error_propuesta'],'')
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_fallo_inicial_preserva_el_texto_pegado(self):
        with patch('core.ai_diario.extraer_operaciones_texto',side_effect=ValueError('Servicio temporalmente no disponible.')):
            respuesta=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':'Mi ejercicio pendiente.'})
        self.assertContains(respuesta,'Mi ejercicio pendiente.')
        self.assertContains(respuesta,'Servicio temporalmente no disponible.')
