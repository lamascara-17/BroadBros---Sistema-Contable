from copy import deepcopy
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from .ciclo_contable import generar_asientos
from .test_ciclo_contable import imagen
from .models import AsientoContable
from .reporte_utils import contexto_estados


def caso():
    return {'empresa_nueva': True, 'metodo_inventario': 'periodico',
            'inventario_inicial': 0, 'fecha_cierre': '2026-10-31',
            'texto_leido': '10/10/2026 Se crea una empresa con 100,000 al contado y 100,000 en máquinas.',
            'operaciones': [
                {'fecha': '2026-10-10', 'tipo': 'aporte_mixto', 'monto_efectivo': 100000,
                 'monto_bienes': 100000, 'texto': 'Empresa con 100,000 al contado y 100,000 en máquinas'},
                {'fecha': '2026-10-15', 'tipo': 'compra_mercaderia', 'monto': 50000,
                 'pago': 'credito', 'texto': 'Compra de mercadería a crédito de 15 días'},
                {'fecha': '2026-10-20', 'tipo': 'venta', 'monto': 100000,
                 'porcentaje_contado': 40, 'texto': 'Venta 60% crédito y 40% contado'},
                {'fecha': '2026-10-25', 'tipo': 'pago_servicios', 'monto': 50000,
                 'detalles': [{'concepto': 'Gastos operativos', 'monto': 50000}],
                 'texto': 'Gastos operativos al contado'},
                {'fecha': '2026-10-31', 'tipo': 'inventario_final', 'monto': 25000,
                 'texto': 'Inventario final al cierre del mes'}]}


class AporteMixtoTests(TestCase):
    def test_aporte_en_especie_no_reduce_caja_y_capital_incluye_ambos_aportes(self):
        with patch('core.ai_diario.extraer_operaciones', return_value=caso()):
            r = self.client.post(reverse('cargar_imagen_diario'), {'imagen_caso': imagen()})
        self.assertRedirects(r, reverse('libro_diario'))
        self.assertEqual(AsientoContable.objects.count(), 5)
        aporte = AsientoContable.objects.order_by('fecha', 'pk').first()
        self.assertEqual(set(aporte.movimientos.values_list('cuenta__codigo', 'tipo', 'monto')),
                         {('10', 'debe', 100000), ('33', 'debe', 100000), ('50', 'haber', 200000)})
        ctx = contexto_estados()
        self.assertEqual(ctx['mayor_datos'][0]['saldo_final'], 90000)
        self.assertEqual(ctx['total_activos'], 275000)
        self.assertEqual(ctx['total_pasivos'], 50000)
        self.assertEqual(ctx['total_patrimonio_con_resultados'], 225000)
        self.assertEqual(ctx['resultado_neto'], 25000)
        self.assertTrue(ctx['esta_balanceado'])

    def test_aportes_incompletos_o_total_inconsistente_no_se_calculan(self):
        for campo, valor in [('monto_bienes', None), ('monto', 100000)]:
            datos = deepcopy(caso())
            datos['operaciones'][0][campo] = valor
            with self.subTest(campo=campo), self.assertRaises(ValueError):
                generar_asientos(datos)
