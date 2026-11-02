"""Contrasta rubros y resultado con libros independientes y exportaciones."""
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from .test_support import AdministrativeTestCase as TestCase
from django.urls import reverse
from openpyxl import load_workbook
from pypdf import PdfReader

from .models import CuentaContable, Movimiento
from .reporte_utils import contexto_estados
from .test_estados_financieros import asiento, novatech
from .views import guardar_importacion


class ConciliacionResultadosTests(TestCase):
    def importar_historico(self):
        entradas = novatech()
        catalogo = {'704': ('4101', 'Ventas', ''),
                    '63': ('6301', 'Alquiler y servicios', ''),
                    '101': ('1101', 'Caja', '')}
        for entrada in entradas:
            for m in entrada['movimientos']:
                if m['codigo'] in catalogo:
                    m['codigo'], m['nombre'], m['subcategoria'] = catalogo[m['codigo']]
        entradas.extend([
            {'fecha': '2025-10-30', 'descripcion': 'Donación recibida', 'movimientos': [
                {'codigo': '2101', 'nombre': 'Inventario de mercaderías', 'tipo_cuenta': 'activo', 'tipo_movimiento': 'debe', 'monto': '1000'},
                {'codigo': '4901', 'nombre': 'Ingresos por Donaciones', 'tipo_cuenta': 'ingreso', 'tipo_movimiento': 'haber', 'monto': '1000'}]},
            {'fecha': '2025-10-31', 'descripcion': 'Pérdida por incendio', 'movimientos': [
                {'codigo': '6901', 'nombre': 'Pérdidas por Incendio', 'tipo_cuenta': 'gasto', 'tipo_movimiento': 'debe', 'monto': '600'},
                {'codigo': '2101', 'nombre': 'Inventario de mercaderías', 'tipo_cuenta': 'activo', 'tipo_movimiento': 'haber', 'monto': '600'}]},
        ])
        # Simular libros históricos sin pasar por una nueva importación PCGE.
        from .models import AsientoContable
        for entrada in entradas:
            a = AsientoContable.objects.create(fecha=entrada['fecha'], descripcion=entrada['descripcion'],
                clase=entrada.get('clase', 'operacion'), flujo_efectivo=entrada.get('flujo_efectivo', 'pendiente'))
            for m in entrada['movimientos']:
                c, _ = CuentaContable.objects.get_or_create(codigo=m['codigo'], defaults={
                    'nombre': m['nombre'], 'tipo': m['tipo_cuenta'], 'subcategoria': m.get('subcategoria','')})
                Movimiento.objects.create(asiento=a, cuenta=c, tipo=m['tipo_movimiento'], monto=m['monto'])

    def test_catalogo_historico_no_confunde_donacion_y_siniestro_con_ventas_y_costo(self):
        self.importar_historico()
        ctx = contexto_estados()
        self.assertEqual(ctx['total_ventas'], 15000)
        self.assertEqual(ctx['total_otros_ingresos'], 1000)
        self.assertEqual(ctx['total_costo_ventas'], 0)
        self.assertEqual(ctx['total_otros_gastos'], 600)
        self.assertEqual(ctx['utilidad_bruta'], 15000)
        self.assertEqual(ctx['resultado_neto'], 11400)
        self.assertEqual(ctx['resultado_segun_libros'], 11400)
        self.assertEqual(ctx['diferencia_resultado'], 0)
        self.assertTrue(ctx['esta_balanceado'])

    def test_utilidad_coincide_con_mayor_balance_y_patrimonio_antes_y_despues_del_cierre(self):
        casos = [novatech(), novatech() + [asiento(31, 'Cierre', [
            ('704', 'debe', 15000), ('63', 'haber', 4000), ('59', 'haber', 11000)], clase='cierre')]]
        for entradas in casos:
            with self.subTest(cierre=len(entradas) == 8):
                guardar_importacion(entradas)
                ctx = contexto_estados()
                neto_mayor = sum((d['total_haber'] - d['total_debe'] for d in ctx['mayor_datos']
                                 if d['cuenta'].tipo in ('ingreso', 'gasto')), Decimal('0'))
                transferido = sum((r['resultado'] for r in ctx['filas_patrimonio'][:-1]), Decimal('0'))
                neto_balance = sum((d['saldo_acreedor'] - d['saldo_deudor'] for d in ctx['bal_comp_datos']
                                   if d['cuenta'].tipo in ('ingreso', 'gasto')), Decimal('0'))
                self.assertEqual(neto_mayor, neto_balance)
                self.assertEqual(ctx['resultado_neto'], neto_balance + transferido)
                self.assertEqual(ctx['resultado_neto'], 11000)
                self.assertEqual(ctx['total_activos'] - ctx['total_pasivos'], ctx['total_patrimonio_con_resultados'])
                self.assertEqual(ctx['totales_patrimonio']['resultado'], ctx['resultado_neto'])
                self.assertEqual(ctx['notas_consistencia'], [])

    def test_clasificacion_explicita_prevalece_sobre_nombre_y_codigo(self):
        self.importar_historico()
        CuentaContable.objects.filter(codigo='6901').update(subcategoria='gasto_operativo')
        ctx = contexto_estados()
        self.assertEqual(ctx['total_gastos_operativos'], 4600)
        self.assertEqual(ctx['total_otros_gastos'], 0)
        self.assertEqual(ctx['resultado_neto'], 11400)

    def test_auxiliar_sin_contrapartida_de_destino_no_pasa_conciliacion(self):
        guardar_importacion(novatech())
        cuenta = CuentaContable.objects.get(codigo='63')
        cuenta.codigo = '9401'
        cuenta.save()
        ctx = contexto_estados()
        self.assertEqual(ctx['resultado_segun_libros'], 11000)
        self.assertEqual(ctx['diferencia_resultado'], 4000)
        self.assertTrue(ctx['notas_consistencia'])
        self.assertContains(self.client.get(reverse('estado_resultados')), 'no coincide')

    def test_inventario_contra_capital_advierte_aunque_la_ecuacion_cuadre(self):
        self.importar_historico()
        from .models import AsientoContable
        a = AsientoContable.objects.create(fecha='2025-10-31', descripcion='Ajuste de inventario')
        Movimiento.objects.create(asiento=a, cuenta=CuentaContable.objects.get(codigo='50'), tipo='debe', monto=100)
        Movimiento.objects.create(asiento=a, cuenta=CuentaContable.objects.get(codigo='2101'), tipo='haber', monto=100)
        ctx = contexto_estados()
        self.assertTrue(ctx['esta_balanceado'])
        self.assertIn('costo de ventas', ctx['nota_resultado'])
        self.assertTrue(any('directamente al patrimonio' in n for n in ctx['notas_consistencia']))

    def test_pantalla_pdf_y_excel_muestran_los_mismos_rubros(self):
        self.importar_historico()
        ctx = contexto_estados()
        pagina = self.client.get(reverse('estado_resultados'))
        self.assertEqual(pagina.context['filas_er'], ctx['filas_er'])
        excel = self.client.post(reverse('reporte_completo'), {'formato': 'excel'})
        libro = load_workbook(BytesIO(excel.content), data_only=True)
        filas = {r[0]: r[1] for r in libro['Estado de Resultados'].iter_rows(values_only=True) if r[0]}
        for concepto, monto, _ in ctx['filas_er']:
            self.assertEqual(Decimal(str(filas[concepto])), monto)
        self.assertEqual(len(libro.sheetnames), 7)
        pdf = self.client.post(reverse('reporte_completo'), {'formato': 'pdf'})
        texto = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
        for importe in ('15,000.00', '1,000.00', '-600.00', '11,400.00'):
            self.assertIn(importe, texto)
