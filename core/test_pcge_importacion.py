from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.urls import reverse
from openpyxl import load_workbook
from pypdf import PdfReader

from .test_support import AdministrativeTestCase as TestCase
from .test_estados_financieros import novatech
from .importacion_general import normalizar_borrador, validar_asientos
from .validacion_contable import preparar_pcge, validar_cuenta, auditar_asientos
from .orientacion import orientar_revision, anio_confirmado
from .models import AsientoContable, CuentaContable
from .views import guardar_importacion
from .reporte_utils import contexto_estados


TEXTO = (Path(__file__).parent/'testdata/novatech_texto_usuario.txt').read_text().strip()


def proveedor_221():
    entradas=novatech()
    for a in entradas:
        for m in a['movimientos']:
            if m['codigo']=='465':m.update(codigo='221',nombre='Proveedores')
    return entradas


class PCGEImportacionTests(TestCase):
    def test_221_de_la_captura_se_corrige_en_compra_y_pago_sin_cambiar_importes(self):
        original=proveedor_221()
        copia=deepcopy(original)
        b=normalizar_borrador({'asientos':original})
        self.assertEqual(original,copia)
        self.assertTrue(all(not a['error_validacion'] for a in b['asientos']))
        proveedores=[m for a in b['asientos'] for m in a['movimientos'] if m['nombre']=='Proveedores']
        self.assertEqual([(m['codigo'],m['monto']) for m in proveedores],[('4654','7000'),('4654','4000')])
        self.assertEqual(preparar_pcge(b['asientos']),b['asientos'])
        guardar_importacion(b['asientos'])
        c=contexto_estados()
        for clave,valor in {'total_ventas':15000,'total_gastos_operativos':4000,'resultado_neto':11000,
                            'total_activos':44000,'total_pasivos':3000,'total_patrimonio_con_resultados':41000,
                            'gran_total_debe':68000,'gran_total_haber':68000}.items():
            self.assertEqual(c[clave],valor,clave)
        self.assertEqual(c['mayor_datos'][0]['saldo_final'],29000)
        self.assertTrue(c['esta_balanceado'])
        self.assertEqual(CuentaContable.objects.filter(codigo='4654').count(),1)
        self.assertFalse(CuentaContable.objects.filter(codigo='221').exists())

    def test_proveedor_comercial_no_se_confunde_con_el_de_equipos(self):
        compras=proveedor_221()[1:2]+proveedor_221()[5:6]
        for a in compras:
            for m in a['movimientos']:
                if m['codigo']=='336':m.update(codigo='201',nombre='Mercaderías')
        b=normalizar_borrador({'asientos':compras})
        self.assertEqual({m['codigo'] for a in b['asientos'] for m in a['movimientos'] if m['nombre']=='Proveedores'},{'421'})
        self.assertTrue(all(not a['error_validacion'] for a in b['asientos']))

    def test_origen_ambiguo_no_se_asigna_a_una_familia_al_azar(self):
        entradas=proveedor_221()
        compra=deepcopy(entradas[1])
        compra['movimientos'][0].update(codigo='201',nombre='Mercaderías')
        entradas.append(compra)
        b=normalizar_borrador({'asientos':entradas})
        self.assertTrue(any('221' in a['error_validacion'] for a in b['asientos']))
        pendientes,_=orientar_revision({'texto_leido':''},b)
        self.assertTrue(any('221' in n for n in pendientes))

    def test_dos_cuentas_distintas_con_nombre_generico_no_se_fusionan(self):
        a=proveedor_221()[1]
        b=deepcopy(a)
        for m in b['movimientos']:
            if m['codigo']=='221':m['codigo']='222'
        result=normalizar_borrador({'asientos':[a,b]})
        codes={m['codigo'] for a in result['asientos'] for m in a['movimientos'] if m['nombre']=='Proveedores'}
        self.assertEqual(len(codes),2)

    def test_411_inventario_se_corrige_solo_si_hay_sustento_de_mercaderias(self):
        a=novatech()[0]
        a['descripcion']='Compra inicial de mercaderías'
        a['movimientos'][0].update(codigo='411',nombre='Inventario')
        b=normalizar_borrador({'asientos':[a]})
        self.assertEqual(b['asientos'][0]['movimientos'][0]['codigo'],'201')
        for codigo,nombre,tipo in [('411','Inventario','activo'),('221','Proveedores','pasivo'),('411','Proveedores','pasivo')]:
            with self.subTest(codigo=codigo,nombre=nombre),self.assertRaises(ValueError):validar_cuenta(codigo,nombre,tipo)

    def test_cuenta_ambigua_se_marca_antes_de_guardar_y_conserva_el_caso(self):
        guardar_importacion(novatech())
        previos=list(AsientoContable.objects.values_list('pk',flat=True))
        a=novatech()[1]
        a['movimientos'][2].update(codigo='221',nombre='Obligación por identificar')
        b=normalizar_borrador({'asientos':[a]})
        self.assertIn('221',b['asientos'][0]['error_validacion'])
        with self.assertRaises(ValueError):guardar_importacion(b['asientos'])
        self.assertEqual(list(AsientoContable.objects.values_list('pk',flat=True)),previos)

    def test_no_se_inventa_inventario_en_el_caso_de_consultoria(self):
        entradas=novatech()
        entradas[0]['movimientos'][0].update(codigo='201',nombre='Mercaderías')
        self.assertTrue(any('no describe existencias' in n for n in auditar_asientos(entradas,TEXTO)))
        with self.assertRaisesMessage(ValueError,'no describe existencias'):guardar_importacion(entradas,fuente=TEXTO)
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_no_se_anade_depreciacion_sin_base_en_novatech(self):
        entradas=novatech()
        ajuste=deepcopy(entradas[-1])
        ajuste['movimientos'][0].update(codigo='68',nombre='Depreciación',monto='100')
        ajuste['movimientos'][1].update(codigo='39',nombre='Depreciación acumulada',tipo_cuenta='activo',monto='100')
        entradas.append(ajuste)
        with self.assertRaisesMessage(ValueError,'sin datos que sustenten ese ajuste'):
            guardar_importacion(entradas,fuente=TEXTO)
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_una_consultora_si_puede_tener_suministros_explicitamente_descritos(self):
        a=deepcopy(novatech()[-1])
        a['movimientos'][0].update(codigo='251',nombre='Suministros',tipo_cuenta='activo',subcategoria='activo_corriente')
        fuente='Una consultora de soporte compra suministros para el almacén por S/ 1,000 al contado.'
        self.assertEqual(auditar_asientos([a],fuente),[])

    def test_caso_original_pide_aclarar_2026_2025_sin_guardar_ni_cambiar_fechas(self):
        b=normalizar_borrador({'asientos':proveedor_221()})
        with patch('core.importacion_general.proponer_caso_general',return_value=b):
            r=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':TEXTO})
        self.assertContains(r,'El encabezado indica octubre de 2026')
        self.assertEqual(len(r.context['pendientes']),1)
        self.assertTrue(all(a['fecha'].startswith('2025') for a in r.context['asientos']))
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_separador_del_esquema_no_es_una_subcategoria_contable(self):
        p=proveedor_221()
        for a in p:
            for m in a['movimientos']:
                if not m['subcategoria']:m['subcategoria']='|'
                if m['codigo']=='101':m['subcategoria']=' |activo_corriente| '
        b=normalizar_borrador({'asientos':p})
        self.assertTrue(all(not a['error_validacion'] for a in b['asientos']))
        guardar_importacion(b['asientos'])
        self.assertEqual(contexto_estados()['resultado_neto'],11000)

    def test_varias_subcategorias_no_se_eligen_al_azar(self):
        p=novatech()
        p[3]['movimientos'][0]['subcategoria']='gasto_operativo|gasto_financiero'
        b=normalizar_borrador({'asientos':p})
        self.assertTrue(b['asientos'][3]['error_validacion'])
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_alquiler_62_de_la_prueba_real_se_separa_de_servicios_63(self):
        p=novatech()
        p[3]['movimientos'][0].update(codigo='62',nombre='Alquileres')
        p[6]['movimientos'][0]['nombre']='Servicios de terceros'
        b=normalizar_borrador({'asientos':p})
        self.assertEqual(b['asientos'][3]['movimientos'][0]['codigo'],'635')
        self.assertEqual(b['asientos'][6]['movimientos'][0]['codigo'],'63')
        self.assertTrue(all(not a['error_validacion'] for a in b['asientos']))
        guardar_importacion(b['asientos'])
        self.assertEqual(contexto_estados()['resultado_neto'],11000)

    def test_aclarar_el_ano_conserva_la_revision_voluntaria_sin_autoguardado(self):
        b=normalizar_borrador({'asientos':proveedor_221()})
        with patch('core.importacion_general.proponer_caso_general',side_effect=[deepcopy(b),deepcopy(b)]):
            inicial=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':TEXTO,'revisar':'on'})
            r=self.client.post(reverse('revisar_importacion'),{'revision_token':inicial.context['revision_token'],
                               'accion':'completar','datos_adicionales':'El año correcto es 2025.'})
        self.assertContains(r,'Revisar ejercicio')
        self.assertEqual(r.context['pendientes'],[])
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_ano_confirmado_2026_concilia_todas_las_fechas_sin_modificar_el_original(self):
        b=normalizar_borrador({'asientos':novatech()})
        for a in b['asientos']:a['fecha']=a['fecha'].replace('2025','2026')
        notas,_=orientar_revision({'texto_leido':TEXTO},b,aclaraciones='El año correcto es 2026.')
        self.assertEqual(notas,[])
        for frase in ('¿El año correcto es 2025?','No es cierto que el año correcto es 2025.'):
            self.assertIsNone(anio_confirmado(frase))

    def test_exportaciones_reales_del_caso_corregido_incluyen_los_siete_reportes(self):
        guardar_importacion(proveedor_221())
        x=self.client.post(reverse('reporte_completo'),{'empresa':'NovaTech','formato':'excel','accion':'descargar'})
        libro=load_workbook(BytesIO(x.content),data_only=True)
        self.assertEqual(len(libro.sheetnames),7)
        self.assertTrue(any(11000 in row for row in libro['Estado de Resultados'].iter_rows(values_only=True)))
        p=self.client.post(reverse('reporte_completo'),{'empresa':'NovaTech','formato':'pdf','accion':'descargar'})
        pdf=PdfReader(BytesIO(p.content));self.assertGreaterEqual(len(pdf.pages),7)
        contenido='\n'.join(pg.extract_text() for pg in pdf.pages)
        self.assertIn('11,000.00',contenido)
