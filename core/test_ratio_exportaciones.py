from io import BytesIO
from decimal import Decimal
from zipfile import ZipFile

from django.test import Client, TestCase as DjangoTestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook
from pypdf import PdfReader

from .test_support import AdministrativeTestCase as TestCase
from .test_estados_financieros import novatech
from .views import guardar_importacion
from .models import AsientoContable, FinancialRatioPeriod
from .ratio_exportacion import comparativo, excel, pdf
from .ratios import DEFINITIONS


class ExportacionesRatiosTests(TestCase):
    def test_excel_comparativo_todos_los_valores_coinciden_con_pantalla(self):
        pagina = self.client.get(reverse('ratios_financieros'))
        r = self.client.get(reverse('ratios_financieros'), {'descargar': 'xlsx'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('.xlsx', r['Content-Disposition'])
        self.assertEqual(r['Cache-Control'], 'private, no-store')
        wb = load_workbook(BytesIO(r.content), data_only=True)
        self.assertEqual(wb.sheetnames, ['Resumen','17 indicadores','Partidas base','Fuentes'])
        ws = wb['17 indicadores']
        for i, row in enumerate(pagina.context['rows'], 7):
            self.assertEqual(ws.cell(i, 1).value, row['label'])
            self.assertEqual(ws.cell(i, 3).value, row['unit'])
            for j, key in enumerate(('previous','own','leader','sector'), 4):
                expected = row['numbers'][key]
                actual = ws.cell(i, j).value
                if expected is None: self.assertEqual(actual, 'N/D')
                else: self.assertAlmostEqual(actual, float(expected), places=10)
                if expected is not None and row['unit'] == '%':
                    self.assertEqual(ws.cell(i, j).number_format, '0.00%')
            self.assertEqual(ws.cell(i, 9).value, row['n'])
            self.assertEqual(ws.cell(i, 10).value, row['formula'])
        self.assertEqual(ws.max_row, 23)
        with ZipFile(BytesIO(r.content)) as z: self.assertIn('xl/charts/chart1.xml', z.namelist())

    def test_exportaciones_respetan_empresa_grupo_tasa_y_deuda(self):
        query = {'empresa':'ASML','lider':'AMAT','year':'2025','tasa':'18','deuda':'current','grupo':'equipment'}
        pagina = self.client.get(reverse('ratios_financieros'), query)
        r = self.client.get(reverse('ratios_financieros'), {**query,'descargar':'xlsx'})
        wb = load_workbook(BytesIO(r.content), data_only=True)
        self.assertAlmostEqual(wb['17 indicadores'].cell(7,5).value, float(pagina.context['rows'][0]['numbers']['own']), places=10)
        for i, row in enumerate(pagina.context['rows'],7):
            expected = row['numbers']['own']
            if expected is not None: self.assertAlmostEqual(wb['17 indicadores'].cell(i,5).value, float(expected), places=10)
        texto = '\n'.join(str(c.value) for row in wb['Resumen'] for c in row)
        self.assertIn('18%', texto)
        self.assertIn('solo CP', texto)
        p = self.client.get(reverse('ratios_financieros'), {**query,'descargar':'pdf'})
        self.assertIn('ASML_2025.pdf', p['Content-Disposition'])
        self.assertIn('ASML', '\n'.join(x.extract_text() for x in PdfReader(BytesIO(p.content)).pages))

    def test_pdf_es_documento_vectorial_organizado_con_todos_los_ratios(self):
        r = self.client.get(reverse('ratios_financieros'), {'descargar':'pdf'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        reader = PdfReader(BytesIO(r.content))
        self.assertEqual(len(reader.pages), 4)
        textos = [p.extract_text() for p in reader.pages]
        self.assertIn('Margen neto: empresa', textos[0])
        self.assertIn('Liquidez y solvencia', textos[1])
        self.assertIn('Gestión y rentabilidad', textos[2])
        self.assertIn('Método y fuentes', textos[3])
        texto = '\n'.join(textos)
        for nombre in ('Liquidez corriente','Prueba ácida','Ciclo de efectivo','Margen EBITDA','ROE'):
            self.assertIn(nombre, texto)
        self.assertIn('36.20%', texto)
        self.assertIn('31.05%', texto)
        self.assertIn('13,059.00', texto)
        self.assertIn('+24.77 pp', texto)
        self.assertNotIn('Calcular escenario', texto)
        self.assertTrue(all(not list(p.images) for p in reader.pages))
        self.assertTrue(reader.pages[-1].get('/Annots'))

    def test_caso_contable_excel_y_pdf_no_mezclan_datos_externos(self):
        guardar_importacion(novatech())
        pagina = self.client.get(reverse('ratios_caso'))
        r = self.client.get(reverse('ratios_caso'), {'descargar':'xlsx'})
        wb = load_workbook(BytesIO(r.content), data_only=True)
        for i, row in enumerate(pagina.context['filas'],7):
            self.assertEqual(wb['17 indicadores'].cell(i,1).value, row['nombre'])
            raw = pagina.context['resultado']['values'][next(d[0] for d in DEFINITIONS if d[1] == row['nombre'])]
            actual = wb['17 indicadores'].cell(i,4).value
            if raw is None: self.assertEqual(actual, 'N/D')
            else: self.assertAlmostEqual(actual,float(raw),places=10)
        p = self.client.get(reverse('ratios_caso'), {'descargar':'pdf'})
        reader = PdfReader(BytesIO(p.content))
        self.assertEqual(len(reader.pages),3)
        texto = '\n'.join(x.extract_text() for x in reader.pages)
        self.assertIn('11,000.00', texto)
        self.assertNotIn('Broadcom',texto)
        self.assertNotIn('NVDA',texto)

    def test_caso_vacio_mantiene_nd_y_csv_sigue_disponible(self):
        r = self.client.get(reverse('ratios_caso'), {'descargar':'xlsx'})
        wb = load_workbook(BytesIO(r.content),data_only=True)
        self.assertTrue(all(wb['17 indicadores'].cell(i,4).value == 'N/D' for i in range(7,24)))
        for ruta in ('ratios_caso','ratios_financieros'):
            for formato in ('xlsx','pdf','csv'):
                self.assertEqual(self.client.get(reverse(ruta),{'descargar':formato}).status_code,200)
        self.assertEqual(AsientoContable.objects.count(),0)
        self.assertEqual(FinancialRatioPeriod.objects.count(),0)

    def test_textos_no_se_ejecutan_como_formulas_y_se_escapan_en_pdf(self):
        pagina = self.client.get(reverse('ratios_financieros'))
        datos = comparativo(pagina.context)
        datos['title'] = '=HYPERLINK("https://ejemplo.invalid","texto") <b>&'
        datos['inputs'][0][0] = '+CMD'
        datos['inputs'][0][-1] = 'file:///no-permitido'
        wb = load_workbook(BytesIO(excel(datos)),data_only=False)
        self.assertEqual(wb['Resumen']['A1'].data_type,'s')
        self.assertEqual(wb['Partidas base']['A7'].data_type,'s')
        self.assertIsNone(wb['Partidas base']['E7'].hyperlink)
        self.assertIn('<b>&','\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf(datos))).pages))

    def test_enlaces_descarga_conservan_configuracion_y_ya_no_imprimen_pantalla(self):
        r = self.client.get(reverse('ratios_financieros'), {'empresa':'AMD','year':'2024','lider':'AVGO'})
        self.assertContains(r, 'descargar=xlsx')
        self.assertContains(r, 'descargar=pdf')
        self.assertContains(r, 'empresa=AMD')
        self.assertContains(r, 'Descargar PDF')
        self.assertNotContains(r, 'Imprimir / PDF')


@override_settings(WORKSPACE_ISOLATION=True)
class ExportacionesAnonimasTests(DjangoTestCase):
    def test_visitantes_sin_login_no_comparten_partidas_exportadas(self):
        from .workspaces import actual
        a, b = Client(), Client()
        self.assertEqual(a.get(reverse('ratios_caso')).status_code,200)
        token = actual.set(a.session['workspace_id'])
        try: guardar_importacion(novatech())
        finally: actual.reset(token)
        ra = a.get(reverse('ratios_caso'), {'descargar':'xlsx'})
        rb = b.get(reverse('ratios_caso'), {'descargar':'xlsx'})
        wa = load_workbook(BytesIO(ra.content), data_only=True)
        wb = load_workbook(BytesIO(rb.content), data_only=True)
        self.assertEqual(wa['Partidas base'].cell(24,2).value,15000)
        self.assertEqual(wb['Partidas base'].cell(24,2).value,'N/D')
        for formato in ('pdf','xlsx'):
            self.assertEqual(b.get(reverse('ratios_financieros'),{'descargar':formato}).status_code,200)
