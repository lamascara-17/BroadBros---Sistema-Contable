import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

from .test_support import AdministrativeTestCase as TestCase
from .test_estados_financieros import novatech
from .models import AsientoContable
from .importacion_general import normalizar_borrador,proponer_caso_general
from .clasificacion import fecha_cierre_del_caso
from .orientacion import orientar_revision
from .views import guardar_importacion
from .reporte_utils import contexto_estados


TEXTO=(Path(__file__).parent/'testdata/mercaderias_cierre_usuario.txt').read_text().strip()


def propuesta(codigo='310'):
    catalogo={'101':('Caja','activo','activo_corriente'),'334':('Vehículo','activo','activo_no_corriente'),
              '501':('Capital social','patrimonio',''),'121':('Clientes','activo','activo_corriente'),
              '421':('Proveedores','pasivo','pasivo_corriente'),'70':('Ventas','ingreso',''),
              '62':('Planilla','gasto','gasto_operativo'),'63':('Servicios básicos','gasto','gasto_operativo'),
              '469':('Servicios por pagar','pasivo','pasivo_corriente'),'69':('Costo de ventas','gasto','costo_ventas'),
              '39':('Depreciación acumulada','activo','activo_no_corriente'),
              codigo:('Inventario','activo','activo_corriente')}
    rows=[('2026-10-01','Aporte inicial',[('101','debe',200000),('334','debe',100000),('501','haber',300000)]),
          ('2026-10-06','Compra de mercadería',[(codigo,'debe',100000),('101','haber',50000),('421','haber',50000)]),
          ('2026-10-11','Venta',[('101','debe',80000),('121','debe',120000),('70','haber',200000)]),
          ('2026-10-16','Pago de planilla',[('62','debe',50000),('101','haber',50000)]),
          ('2026-10-16','Servicios pendientes',[('63','debe',10000),('469','haber',10000)]),
          (None,'Ajuste de inventario final: 50000',[('69','debe',50000),(codigo,'haber',50000)]),
          (None,'Depreciación mensual',[('62','debe','833.33'),('39','haber','833.33')])]
    asientos=[]
    for i,(fecha,glosa,lineas) in enumerate(rows):
        movs=[]
        for code,lado,monto in lineas:
            nombre,tipo,sub=catalogo[code]
            if i==6 and code=='62':nombre='Depreciación del vehículo'
            movs.append({'codigo':code,'nombre':nombre,'tipo_cuenta':tipo,'subcategoria':sub,'tipo_movimiento':lado,'monto':str(monto)})
        asientos.append({'fecha':fecha,'descripcion':glosa,'clase':'apertura' if i==0 else 'operacion',
                         'flujo_efectivo':'financiacion' if i==0 else 'operacion','movimientos':movs})
    return {'asientos':asientos,'pendientes':[],'supuestos':[]}


def respuesta(datos):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(datos)))])


class NormalizacionInventarioTests(TestCase):
    @override_settings(GROQ_API_KEY='solo-prueba')
    def test_groq_411_y_310_se_normalizan_antes_de_la_decision_de_guardado(self):
        for codigo in ('411','310'):
            with self.subTest(codigo=codigo),patch('core.importacion_general.Groq'),patch('core.importacion_general.solicitar_json',return_value=respuesta(propuesta(codigo))) as ia:
                b=proponer_caso_general({'texto_leido':TEXTO},None)
            self.assertEqual(ia.call_count,1)
            inv=[m for a in b['asientos'] for m in a['movimientos'] if m['nombre']=='Inventario']
            self.assertEqual([m['codigo'] for m in inv],['201','201'])
            self.assertEqual([a['fecha'] for a in b['asientos'][-2:]],['2026-10-31','2026-10-31'])
            self.assertEqual(b['pendientes'],[])
            self.assertTrue(all(not a['error_validacion'] for a in b['asientos']))
            self.assertEqual(AsientoContable.objects.count(),0)

    def test_codigos_incorrectos_distintos_en_compra_y_ajuste_usan_la_misma_cuenta(self):
        p=propuesta('411');p['asientos'][5]['movimientos'][1]['codigo']='310'
        b=normalizar_borrador(p,fuente=TEXTO)
        self.assertEqual(b['asientos'][1]['movimientos'][0]['codigo'],b['asientos'][5]['movimientos'][1]['codigo'])

    def test_un_codigo_correcto_se_conserva_y_se_reutiliza(self):
        p=propuesta('201');p['asientos'][5]['movimientos'][1]['codigo']='310'
        b=normalizar_borrador(p,fuente=TEXTO)
        self.assertEqual([b['asientos'][i]['movimientos'][j]['codigo'] for i,j in [(1,0),(5,1)]],['201','201'])

    def test_materia_prima_y_productos_terminados_no_se_convierten_en_mercaderias(self):
        for fuente,codigo in [('Compra de materia prima','241'),('Compra de productos terminados','211')]:
            p=propuesta('310');p['asientos']=p['asientos'][1:2];p['asientos'][0]['descripcion']='Compra de inventario'
            b=normalizar_borrador(p,fuente=fuente)
            self.assertEqual(b['asientos'][0]['movimientos'][0]['codigo'],codigo)
        p=propuesta('241');p['asientos']=p['asientos'][1:2];p['asientos'][0]['descripcion']='Compra de materia prima'
        self.assertEqual(normalizar_borrador(p,fuente='Compra de materia prima')['asientos'][0]['movimientos'][0]['codigo'],'241')

    def test_inventario_ambiguo_no_se_reclasifica_solo_por_ser_activo(self):
        p=propuesta('310');p['asientos']=p['asientos'][1:2];p['asientos'][0]['descripcion']='Compra de inventario'
        b=normalizar_borrador(p,fuente='Compra de inventario sin indicar su naturaleza.')
        self.assertEqual(b['asientos'][0]['movimientos'][0]['codigo'],'310')
        self.assertTrue(b['asientos'][0]['error_validacion'])
        self.assertTrue(any('tipo de inventario' in n for n in b['pendientes']))

    def test_dos_tipos_de_inventario_requieren_contexto_local(self):
        p=propuesta('310');p['asientos']=p['asientos'][1:2];p['asientos'][0]['descripcion']='Compra de inventario'
        fuente='La empresa compra mercaderías. Compra de materias primas.'
        self.assertTrue(normalizar_borrador(p,fuente=fuente)['asientos'][0]['error_validacion'])
        p['asientos'][0]['descripcion']='Compra de materias primas'
        self.assertEqual(normalizar_borrador(p,fuente=fuente)['asientos'][0]['movimientos'][0]['codigo'],'241')

    def test_sin_fecha_de_cierre_inequivoca_el_error_indica_6_y_7(self):
        for fuente in ('Al cierre del mes se ajusta el inventario.',TEXTO+'\n01/11/2026: otra operación.'):
            b=normalizar_borrador(propuesta(),fuente=fuente)
            self.assertFalse(b['asientos'][5]['fecha']);self.assertFalse(b['asientos'][6]['fecha'])
            self.assertIn('asiento 6',b['asientos'][5]['error_validacion'])
            self.assertIn('asiento 7',b['asientos'][6]['error_validacion'])
            self.assertNotIn('asiento 1',b['asientos'][5]['error_validacion'])
        self.assertEqual(str(fecha_cierre_del_caso({'texto_leido':TEXTO})),'2026-10-31')

    def test_planilla_y_depreciacion_no_comparten_la_cuenta_62(self):
        b=normalizar_borrador(propuesta(),fuente=TEXTO)
        self.assertEqual(b['asientos'][3]['movimientos'][0]['codigo'],'62')
        self.assertEqual(b['asientos'][6]['movimientos'][0]['codigo'],'68')

    def test_colision_no_resoluble_se_ve_en_revision(self):
        p=propuesta();p['asientos'][4]['movimientos'][1].update(codigo='63',nombre='Obligación sin identificar',tipo_cuenta='pasivo')
        b=normalizar_borrador(p,fuente=TEXTO)
        self.assertIn('asientos 5',b['asientos'][4]['error_validacion'])
        self.assertIn('nombres o clasificaciones distintos',b['asientos'][4]['error_validacion'])

    def test_ajuste_con_fecha_valida_pero_distinta_del_cierre_se_advierte(self):
        p=propuesta();p['asientos'][5]['fecha']='2026-10-30'
        b=normalizar_borrador(p,fuente=TEXTO)
        pendientes,_=orientar_revision({'texto_leido':TEXTO},b)
        self.assertTrue(any('Asiento 6' in n and '2026-10-31' in n for n in pendientes))

    def test_cierre_anual_no_reubica_ajustes_mensuales_de_otros_periodos(self):
        from .validacion_contable import auditar_asientos
        b=normalizar_borrador(propuesta(),fuente=TEXTO)
        fuente=TEXTO+'\nFecha de cierre: 31/12/2026.'
        self.assertEqual(str(fecha_cierre_del_caso({'texto_leido':fuente})),'2026-12-31')
        self.assertIsNone(fecha_cierre_del_caso({'texto_leido':fuente},solo_periodo_unico=True))
        self.assertFalse(any('Corrija la fecha' in n for n in auditar_asientos(b['asientos'],fuente)))

    def test_propuesta_incorrecta_no_reemplaza_el_caso_activo(self):
        guardar_importacion(novatech())
        ids=list(AsientoContable.objects.values_list('pk',flat=True))
        p=propuesta();p['asientos'][0]['movimientos'][0]['monto']='200001'
        for opcion in ({},{'revisar':'on'}):
            with patch('core.importacion_general.proponer_caso_general',return_value=deepcopy(p)):
                r=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':TEXTO,**opcion})
            self.assertContains(r,'Revisar ejercicio')
            self.assertEqual(list(AsientoContable.objects.values_list('pk',flat=True)),ids)

    def test_inventario_y_proveedor_incorrectos_se_corrigen_juntos(self):
        p=propuesta()
        p['asientos'][1]['movimientos'][2]['codigo']='221'
        b=normalizar_borrador(p,fuente=TEXTO)
        self.assertEqual(b['asientos'][1]['movimientos'][0]['codigo'],'201')
        self.assertEqual(b['asientos'][1]['movimientos'][2]['codigo'],'421')
        self.assertTrue(all(not a['error_validacion'] for a in b['asientos']))

    def test_caso_normalizado_reconcilia_inventario_utilidad_y_balance(self):
        b=normalizar_borrador(propuesta(),fuente=TEXTO)
        guardar_importacion(b['asientos'],fuente=TEXTO,fecha_cierre=fecha_cierre_del_caso({'texto_leido':TEXTO}))
        c=contexto_estados()
        self.assertEqual(c['resultado_neto'],Decimal('89166.67'))
        self.assertEqual(c['total_activos'],Decimal('449166.67'))
        self.assertEqual(c['total_pasivos'],60000)
        self.assertTrue(c['esta_balanceado'])
