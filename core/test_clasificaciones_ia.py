from copy import deepcopy
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from .test_estados_financieros import novatech
from .importacion_general import normalizar_borrador, validar_asientos
from .models import AsientoContable
from .reporte_utils import contexto_estados


class ClasificacionesIATests(TestCase):
    def test_novatech_con_etiquetas_financieras_equivalentes_se_guarda(self):
        asientos = deepcopy(novatech())
        for a in asientos:
            for m in a['movimientos']:
                if m['tipo_cuenta'] == 'activo':
                    m['tipo_cuenta'] = 'Activo no corriente' if m['codigo'] == '336' else 'ACTIVOS'
                    m['subcategoria'] = 'General' if m['codigo'] == '336' else 'Corriente'
                elif m['tipo_cuenta'] == 'pasivo':
                    m['tipo_cuenta'], m['subcategoria'] = 'Pasivos', 'Pasivo corriente'
                elif m['tipo_cuenta'] == 'patrimonio':
                    m['tipo_cuenta'], m['subcategoria'] = 'Patrimonio neto', 'Capital social'
        borrador = normalizar_borrador({'asientos': asientos})
        self.assertTrue(all(not a['error_validacion'] for a in borrador['asientos']))
        with patch('core.importacion_general.proponer_caso_general', return_value=borrador):
            r = self.client.post(reverse('cargar_texto_diario'), {'texto_caso': 'Caso NovaTech completo'})
        self.assertRedirects(r, reverse('libro_diario'))
        self.assertEqual(AsientoContable.objects.count(), 7)
        ctx = contexto_estados()
        self.assertEqual(ctx['mayor_datos'][0]['saldo_final'], 29000)
        self.assertEqual(ctx['total_activo_no_corriente'], 12000)
        self.assertEqual(ctx['total_pasivo_corriente'], 3000)
        self.assertEqual(ctx['resultado_neto'], 11000)
        self.assertTrue(ctx['esta_balanceado'])

    def test_etiquetas_desconocidas_y_clasificaciones_contradictorias_se_rechazan(self):
        for tipo, sub in [('activo', 'inventada'), ('gasto', 'pasivo_corriente'),
                          ('pasivo', 'activo_corriente'), ('desconocida', '')]:
            entradas = deepcopy(novatech())
            entradas[0]['movimientos'][0].update(tipo_cuenta=tipo, subcategoria=sub)
            with self.subTest(tipo=tipo, sub=sub), self.assertRaises(ValueError):
                validar_asientos(entradas)
