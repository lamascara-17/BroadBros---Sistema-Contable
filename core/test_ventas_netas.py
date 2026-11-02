"""Regresión: ventas identificadas como otros ingresos, sin alterar libros."""
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from django.urls import reverse
from openpyxl import load_workbook
from pypdf import PdfReader

from .test_support import AdministrativeTestCase as TestCase
from .models import AsientoContable, CuentaContable, Movimiento
from .clasificacion import rubro_resultados
from .validacion_contable import preparar_pcge, validar_cuenta
from .importacion_general import normalizar_borrador
from .reporte_utils import contexto_estados
from .ratios_caso import calcular_caso
from .respaldos import serializar_caso, validar_respaldo, crear_respaldo, restaurar
from .bot_calculos import respuesta_calculada
from .views import guardar_importacion


class VentasNetasTests(TestCase):
    def sembrar(self, codigo='70', nombre='Ventas', sub='otro_ingreso'):
        catalogo = [('101', 'Caja', 'activo', ''), ('20', 'Mercaderías', 'activo', ''),
                    ('121', 'Clientes', 'activo', ''), ('50', 'Capital', 'patrimonio', ''),
                    ('59', 'Resultados acumulados', 'patrimonio', ''),
                    (codigo, nombre, 'ingreso', sub),
                    ('69', 'Costo de ventas', 'gasto', 'costo_ventas'),
                    ('67', 'Intereses', 'gasto', 'gasto_financiero')]
        self.cuentas = {c: CuentaContable.objects.create(codigo=c, nombre=n, tipo=t, subcategoria=s)
                        for c, n, t, s in catalogo}
        self.agregar('Apertura', [('101', 'debe', 5000), ('20', 'debe', 1000), ('50', 'haber', 6000)], 'apertura')
        self.agregar('Venta mixta', [('101', 'debe', 1000), ('121', 'debe', 1000), (codigo, 'haber', 2000)])
        self.agregar('Costo de la mercadería vendida', [('69', 'debe', 600), ('20', 'haber', 600)])
        self.agregar('Intereses pagados', [('67', 'debe', 50), ('101', 'haber', 50)])

    def agregar(self, descripcion, lineas, clase='operacion'):
        a = AsientoContable.objects.create(fecha='2025-11-01', descripcion=descripcion, clase=clase)
        for c, lado, monto in lineas:
            Movimiento.objects.create(asiento=a, cuenta=self.cuentas[c], tipo=lado, monto=monto)

    def test_reproduce_captura_y_corrige_rubros_sin_reescribir_datos(self):
        self.sembrar()
        original = serializar_caso()
        ctx = contexto_estados()
        for clave, valor in {'total_ventas': 2000, 'total_otros_ingresos': 0,
                            'total_costo_ventas': 600, 'utilidad_bruta': 1400,
                            'utilidad_operativa': 1400, 'total_gastos_financieros': 50,
                            'resultado_neto': 1350, 'diferencia_resultado': 0,
                            'total_activos': 7350, 'total_patrimonio_con_resultados': 7350}.items():
            self.assertEqual(ctx[clave], valor, clave)
        self.assertEqual(ctx['notas_consistencia'], [])
        self.assertTrue(ctx['esta_balanceado'])
        self.assertEqual(serializar_caso(), original)
        self.assertEqual(CuentaContable.objects.get(codigo='70').subcategoria, 'otro_ingreso')

    def test_catalogo_historico_con_codigo_distinto_no_oculta_ventas(self):
        self.sembrar('4101')
        c = calcular_caso()
        self.assertEqual(c['contexto']['total_ventas'], 2000)
        self.assertEqual(c['resultado']['inputs']['revenue'], Decimal('2000'))
        self.assertEqual(c['resultado']['inputs']['credit_revenue'], Decimal('1000'))
        self.assertEqual(c['resultado']['values']['net_margin'], Decimal('0.675'))

    def test_devoluciones_y_descuentos_reducen_ventas_sin_duplicar_gastos(self):
        self.sembrar()
        for codigo, nombre, importe in [('709', 'Devoluciones sobre ventas', 100),
                                         ('741', 'Descuentos comerciales concedidos', 50)]:
            self.cuentas[codigo] = CuentaContable.objects.create(codigo=codigo, nombre=nombre, tipo='ingreso', subcategoria='otro_ingreso')
            self.agregar(nombre, [(codigo, 'debe', importe), ('121', 'haber', importe)])
        ctx = contexto_estados()
        self.assertEqual(ctx['total_ventas'], 1850)
        self.assertEqual(ctx['utilidad_bruta'], 1250)
        self.assertEqual(ctx['resultado_neto'], 1200)
        self.assertEqual(ctx['total_otros_ingresos'], 0)
        self.assertEqual(ctx['total_gastos_operativos'], 0)
        self.assertEqual(ctx['diferencia_resultado'], 0)

    def test_donacion_intereses_y_venta_de_activo_no_son_ventas_ordinarias(self):
        for codigo, nombre in [('75', 'Donación recibida'), ('77', 'Intereses sobre ventas'),
                               ('756', 'Venta de activo fijo'), ('7564', 'Enajenación de equipo de uso propio'),
                               ('752', 'Comisiones por ventas'), ('71', 'Variación de producción almacenada'),
                               ('72', 'Producción de activo inmovilizado')]:
            with self.subTest(nombre=nombre):
                c = SimpleNamespace(codigo=codigo, nombre=nombre, tipo='ingreso', subcategoria='')
                self.assertEqual(rubro_resultados(c), 'otros_ingresos')
        c = SimpleNamespace(codigo='675', nombre='Descuentos por pronto pago', tipo='gasto', subcategoria='')
        self.assertEqual(rubro_resultados(c), 'gastos_financieros')

    def test_borradores_nuevos_corrigen_etiqueta_y_no_recodifican_venta_activo(self):
        self.sembrar()
        datos = serializar_caso()['asientos']
        original = deepcopy(datos)
        borrador = normalizar_borrador({'asientos': datos})
        self.assertTrue(all(not a['error_validacion'] for a in borrador['asientos']))
        self.assertEqual(borrador['asientos'][1]['movimientos'][-1]['subcategoria'], '')
        guardar_importacion(datos)
        self.assertEqual(CuentaContable.objects.get(codigo='70').subcategoria, '')
        self.assertEqual(contexto_estados()['total_ventas'], 2000)
        self.assertEqual(datos, original)
        activo = [{'movimientos': [{'codigo': '756', 'nombre': 'Venta de activo fijo', 'tipo_cuenta': 'ingreso', 'subcategoria': 'otro_ingreso'}]}]
        self.assertEqual(preparar_pcge(activo), activo)
        validar_cuenta('756', 'Venta de activo fijo', 'ingreso')
        validar_cuenta('741', 'Descuentos sobre ventas', 'ingreso')

    def test_cierre_no_borra_ventas_utilidades_ni_ratios(self):
        self.sembrar()
        self.agregar('Cierre de resultados', [('70', 'debe', 2000), ('69', 'haber', 600),
                      ('67', 'haber', 50), ('59', 'haber', 1350)], 'cierre')
        c = calcular_caso()
        self.assertEqual(c['contexto']['total_ventas'], 2000)
        self.assertEqual(c['contexto']['utilidad_bruta'], 1400)
        self.assertEqual(c['contexto']['resultado_neto'], 1350)
        self.assertEqual(c['contexto']['diferencia_resultado'], 0)
        self.assertEqual(c['resultado']['values']['net_margin'], Decimal('0.675'))
        self.assertEqual(c['contexto']['resultados_acumulados'], 0)

    def test_pantalla_pdf_excel_y_csv_coinciden(self):
        self.sembrar()
        ctx = contexto_estados()
        pagina = self.client.get(reverse('estado_resultados'))
        self.assertEqual(pagina.context['filas_er'], ctx['filas_er'])
        xlsx = self.client.post(reverse('reporte_completo'), {'formato': 'excel'})
        libro = load_workbook(BytesIO(xlsx.content), data_only=True)
        self.assertEqual(len(libro.sheetnames), 7)
        filas = {r[0]: r[1] for r in libro['Estado de Resultados'].iter_rows(values_only=True) if r[0]}
        for nombre, valor, _ in ctx['filas_er']:
            self.assertEqual(Decimal(str(filas[nombre])), valor)
        pdf = self.client.post(reverse('reporte_completo'), {'formato': 'pdf'})
        texto = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
        for importe in ('2,000.00', '1,400.00', '1,350.00', '-600.00', '-50.00'):
            self.assertIn(importe, texto)
        ratios = self.client.get(reverse('ratios_caso'))
        csv = self.client.get(reverse('ratios_caso'), {'descargar': 'csv'}).content.decode('utf-8-sig')
        for fila in ratios.context['filas']:
            self.assertIn(fila['valor'], csv)
        self.assertIn('67.50%', csv)

    def test_json_historico_se_recupera_con_ventas_correctas(self):
        self.sembrar()
        original = serializar_caso()
        validar_respaldo(original)
        copia = crear_respaldo()
        restaurar(copia)
        self.assertEqual(serializar_caso(), original)
        self.assertEqual(contexto_estados()['total_ventas'], 2000)

    def test_nonobot_distingue_ventas_y_cada_nivel_de_utilidad(self):
        self.sembrar()
        for pregunta, importe, nombre in [('Cuáles son las ventas netas', '2,000.00', 'ventas netas'),
                                         ('Dime mi utilidad bruta', '1,400.00', 'utilidad bruta'),
                                         ('Cuál es mi utilidad operativa', '1,400.00', 'utilidad operativa'),
                                         ('Cuánto es mi utilidad antes de impuestos', '1,350.00', 'antes de impuestos'),
                                         ('Cuál es mi utilidad neta', '1,350.00', 'resultado neto')]:
            with self.subTest(pregunta=pregunta):
                respuesta = respuesta_calculada(pregunta)
                self.assertIn(importe, respuesta)
                self.assertIn(nombre, respuesta)

    def test_un_caso_sin_ventas_no_inventa_ingresos(self):
        self.sembrar()
        AsientoContable.objects.filter(descripcion='Venta mixta').delete()
        ctx = contexto_estados()
        self.assertEqual(ctx['total_ventas'], 0)
        self.assertEqual(ctx['resultado_neto'], -650)
        self.assertIn('ventas netas son cero', ctx['nota_resultado'])
        self.assertEqual(calcular_caso()['resultado']['values']['net_margin'], None)
