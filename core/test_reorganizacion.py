import json
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings
from .importacion_general import organizar_lectura, proponer_caso_general, PropuestaInvalida, normalizar_borrador
from .test_estados_financieros import novatech


def respuesta(datos, fin='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=fin, message=SimpleNamespace(content=json.dumps(datos)))])


def propuesta():
    return normalizar_borrador({'asientos': novatech(), 'pendientes': [], 'supuestos': []})


@override_settings(GROQ_API_KEY='prueba')
class ReorganizacionTests(TestCase):
    def setUp(self):
        cliente = patch('core.importacion_general.Groq')
        cliente.start()
        self.addCleanup(cliente.stop)

    def test_bloques_conservan_todos_los_caracteres(self):
        original = 'El 01/10/2025 aporta S/ 30,000.\nCompra por S/ 12,000; paga 5,000 y debe 7,000.'
        bloques = ['El 01/10/2025 aporta S/ 30,000.\n', 'Compra por S/ 12,000; paga 5,000 y debe 7,000.']
        with patch('core.importacion_general.solicitar_json', return_value=respuesta({'bloques': bloques})) as solicitar:
            resultado = organizar_lectura({'texto_leido': original})
        self.assertEqual(resultado['texto_leido'], original)
        self.assertEqual(''.join(resultado['bloques_lectura']), original)
        self.assertEqual(solicitar.call_count, 1)

    def test_descarta_cambios_omisiones_reordenamientos_y_truncamientos(self):
        original = 'Fecha 01/10/2025. S/ 12,000 IVA incluido. Paga 5,000 y debe 7,000.'
        variantes = [['Fecha 02/10/2025. S/ 12,000 IVA incluido. Paga 5,000 y debe 7,000.'],
                     [original.replace('12,000', '17,000')], [original.replace('IVA incluido.', '')],
                     [original[20:], original[:20]], [original, ' Suponemos IVA 18%.'], [], 'texto']
        for bloques in variantes:
            with self.subTest(bloques=bloques), patch('core.importacion_general.solicitar_json', return_value=respuesta({'bloques': bloques})):
                with self.assertRaises(ValueError): organizar_lectura({'texto_leido': original})
        with patch('core.importacion_general.solicitar_json', return_value=respuesta({'bloques': [original]}, 'length')):
            with self.assertRaises(ValueError): organizar_lectura({'texto_leido': original})

    def test_caso_correcto_no_consume_otro_intento(self):
        inicial = propuesta()
        with patch('core.importacion_general._proponer_base', return_value=inicial) as analizar, patch('core.importacion_general.organizar_lectura') as organizar:
            self.assertEqual(proponer_caso_general({'texto_leido': 'Caso NovaTech'}, None), inicial)
            analizar.assert_called_once()
            organizar.assert_not_called()

    def test_rescate_por_formato_preserva_original_y_aclaraciones(self):
        datos = {'texto_leido': 'Lectura original completa.'}
        organizados = {**datos, 'bloques_lectura': ['Lectura original completa.']}
        with patch('core.importacion_general._proponer_base', side_effect=[PropuestaInvalida('JSON inválido'), propuesta()]) as analizar, patch('core.importacion_general.organizar_lectura', return_value=organizados) as organizar:
            resultado = proponer_caso_general(datos, '18', 'Aclaración del usuario')
        self.assertTrue(resultado['lectura_reorganizada'])
        self.assertEqual(analizar.call_count, 2)
        self.assertEqual(analizar.call_args.args, (organizados, '18', 'Aclaración del usuario'))
        organizar.assert_called_once_with(datos)
        self.assertEqual(datos, {'texto_leido': 'Lectura original completa.'})

    def test_operacion_omitida_activa_un_solo_rescate(self):
        datos = {'texto_leido': 'El 01/10/2025 aporta 30000. El 05/10/2025 compra por 12000.'}
        incompleto = normalizar_borrador({'asientos': novatech()[:1], 'pendientes': [], 'supuestos': []})
        with patch('core.importacion_general._proponer_base', side_effect=[incompleto, propuesta()]) as analizar, patch('core.importacion_general.organizar_lectura', return_value=datos) as organizar:
            self.assertTrue(proponer_caso_general(datos, None)['lectura_reorganizada'])
        self.assertEqual(analizar.call_count, 2)
        organizar.assert_called_once()

    def test_segundo_analista_recibe_bloques_y_original_sin_otra_imagen(self):
        original = 'El 01/10/2025 aporta S/ 30,000.'
        from .importacion_general import serializar_asientos
        valido = {'asientos': serializar_asientos(novatech()[:1]), 'pendientes': [], 'supuestos': []}
        with patch('core.importacion_general.solicitar_json', side_effect=[
                respuesta({'formato': 'incorrecto'}), respuesta({'bloques': [original]}), respuesta(valido)]) as solicitar:
            resultado = proponer_caso_general({'texto_leido': original}, None)
        self.assertEqual(len(resultado['asientos']), 1)
        self.assertTrue(resultado['lectura_reorganizada'])
        self.assertEqual(solicitar.call_count, 3)
        contenido = json.loads(solicitar.call_args.kwargs['messages'][1]['content'])
        self.assertEqual(contenido['ejercicio'], {'texto_leido': original, 'operaciones_organizadas': [original]})

    def test_no_reintenta_por_cuota_conexion_o_lectura_incompleta(self):
        for error in ('Groq alcanzó su límite de uso.', 'No se pudo conectar con Groq.'):
            with patch('core.importacion_general._proponer_base', side_effect=ValueError(error)), patch('core.importacion_general.organizar_lectura') as organizar:
                with self.assertRaisesMessage(ValueError, error): proponer_caso_general({'texto_leido': 'Caso'}, None)
                organizar.assert_not_called()
        with patch('core.importacion_general._proponer_base') as analizar, patch('core.importacion_general.organizar_lectura') as organizar:
            with self.assertRaises(ValueError): proponer_caso_general({'texto_leido': 'Parcial', 'lectura_incompleta': True}, None)
            analizar.assert_not_called(); organizar.assert_not_called()

    def test_rescate_fallido_conserva_el_error_o_borrador_anterior(self):
        with patch('core.importacion_general._proponer_base', side_effect=PropuestaInvalida('Error original')), patch('core.importacion_general.organizar_lectura', side_effect=ValueError('Cambió un importe')):
            with self.assertRaisesMessage(ValueError, 'Error original'): proponer_caso_general({'texto_leido': 'Caso'}, None)
        inicial = propuesta(); inicial['asientos'][0]['error_validacion'] = 'No cuadra.'
        with patch('core.importacion_general._proponer_base', return_value=inicial), patch('core.importacion_general.organizar_lectura', side_effect=RuntimeError('Fallo')):
            self.assertEqual(proponer_caso_general({'texto_leido': 'Caso'}, None), inicial)
