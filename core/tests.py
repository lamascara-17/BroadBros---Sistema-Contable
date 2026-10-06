from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from .models import AsientoContable, CuentaContable, Movimiento


class FrontendFlowTests(TestCase):
    def setUp(self):
        self.caja = CuentaContable.objects.create(codigo='10', nombre='Caja "principal" <b> & bancos', tipo='activo')
        self.capital = CuentaContable.objects.create(codigo='50', nombre='Capital', tipo='patrimonio')
        self.asiento = AsientoContable.objects.create(fecha='2026-10-05', descripcion='Aporte inicial')
        Movimiento.objects.create(asiento=self.asiento, cuenta=self.caja, tipo='debe', monto=100)
        Movimiento.objects.create(asiento=self.asiento, cuenta=self.capital, tipo='haber', monto=100)

    def payload(self, **changes):
        data = {'fecha': '2026-10-06', 'descripcion': 'Aporte actualizado', 'num_movimientos': '2',
                'cuenta_0': str(self.caja.pk), 'tipo_0': 'debe', 'monto_0': '150.25',
                'cuenta_1': str(self.capital.pk), 'tipo_1': 'haber', 'monto_1': '150.25'}
        data.update(changes)
        return data

    def test_all_screens_render_with_and_without_movements(self):
        for empty in (False, True):
            if empty:
                AsientoContable.objects.all().delete()
            for name in ('index', 'registrar_asiento', 'libro_diario', 'libro_mayor',
                         'balance_comprobacion', 'estado_resultados', 'balance_general',
                         'reporte_completo', 'gestionar_cuentas', 'cargar_imagen_diario'):
                with self.subTest(screen=name, empty=empty):
                    response = self.client.get(reverse(name))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'assistant-panel')

    def test_balanced_edit_replaces_header_and_details(self):
        response = self.client.post(reverse('editar_asiento', args=[self.asiento.pk]), self.payload())
        self.assertRedirects(response, reverse('libro_diario'))
        self.asiento.refresh_from_db()
        self.assertEqual(self.asiento.descripcion, 'Aporte actualizado')
        self.assertEqual(self.asiento.total_debe, Decimal('150.25'))
        self.assertEqual(self.asiento.movimientos.count(), 2)
        self.assertTrue(self.asiento.esta_balanceado)

    def test_invalid_edit_preserves_original_asiento(self):
        cases = [{'monto_1': '50'}, {'num_movimientos': '1'}, {'cuenta_0': '999999'},
                 {'fecha': 'invalid'}, {'tipo_0': 'otro'}, {'monto_0': 'NaN'},
                 {'monto_0': '-1'}, {'monto_0': '0.001'}, {'num_movimientos': 'bad'}]
        original_ids = list(self.asiento.movimientos.values_list('pk', flat=True))
        for changes in cases:
            with self.subTest(changes=changes):
                self.client.post(reverse('editar_asiento', args=[self.asiento.pk]), self.payload(**changes))
                self.asiento.refresh_from_db()
                self.assertEqual(self.asiento.descripcion, 'Aporte inicial')
                self.assertEqual(list(self.asiento.movimientos.values_list('pk', flat=True)), original_ids)

    def test_register_balanced_asiento(self):
        response = self.client.post(reverse('registrar_asiento'), self.payload())
        self.assertRedirects(response, reverse('libro_diario'))
        self.assertEqual(AsientoContable.objects.count(), 2)

    def test_excel_download(self):
        response = self.client.post(reverse('reporte_completo'), {'empresa': 'Prueba', 'formato': 'excel', 'accion': 'descargar'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response['Content-Type'])
        self.assertTrue(response.content.startswith(b'PK'))

    def test_pdf_download(self):
        response = self.client.post(reverse('reporte_completo'), {'empresa': 'Prueba', 'formato': 'pdf', 'accion': 'descargar'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
