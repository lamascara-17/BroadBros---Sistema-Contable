from copy import deepcopy
from .test_support import AdministrativeTestCase
from .test_estados_financieros import novatech
from .importacion_general import normalizar_borrador
from .validacion_contable import preparar_pcge, auditar_asientos
from .views import guardar_importacion
from .reporte_utils import contexto_estados
from .models import AsientoContable


PAGO='El día 26 de octubre de 2025, la empresa paga S/ 4,000 al proveedor como parte de la deuda por los equipos adquiridos.'
COBRO='El día 22 de octubre de 2025, el cliente cancela S/ 3,000 de la deuda pendiente por los servicios prestados.'
SERVICIOS='El día 30 de octubre de 2025, se pagan servicios básicos de la oficina por un total de S/ 1,000 en efectivo.'


class OperacionesDocumentadasTests(AdministrativeTestCase):
    def test_pago_invertido_literal_resta_caja_y_deuda_sin_cambiar_cifras(self):
        entradas=novatech()
        for a in entradas:
            for m in a['movimientos']:
                if m['codigo']=='465':m.update(codigo='42',nombre='Proveedores')
        pago=entradas[5];pago['fuente']=PAGO
        pago['descripcion']='Pago parcial a proveedor de equipos'
        for m in pago['movimientos']:m['tipo_movimiento']='haber' if m['tipo_movimiento']=='debe' else 'debe'
        original=deepcopy(entradas)
        b=normalizar_borrador({'asientos':entradas},fuente=PAGO)
        self.assertEqual(entradas,original)
        self.assertTrue(any('sentido del pago' in n for n in b['supuestos']))
        self.assertEqual(AsientoContable.objects.count(),0)
        self.assertTrue(all(not a['error_validacion'] for a in b['asientos']))
        self.assertEqual([m['codigo'] for m in b['asientos'][5]['movimientos']],['4654','101'])
        guardar_importacion(b['asientos'])
        c=contexto_estados()
        self.assertEqual(c['mayor_datos'][0]['saldo_final'],29000)
        self.assertEqual(c['total_pasivos'],3000)
        self.assertEqual(c['resultado_neto'],11000)

    def test_cobro_invertido_literal_se_corrige(self):
        a=novatech()[4];a['fuente']=COBRO
        for m in a['movimientos']:m['tipo_movimiento']='haber' if m['tipo_movimiento']=='debe' else 'debe'
        b=normalizar_borrador({'asientos':[a]},fuente=COBRO)
        self.assertEqual([m['tipo_movimiento'] for m in b['asientos'][0]['movimientos']],['debe','haber'])
        self.assertTrue(any('sentido del cobro' in n for n in b['supuestos']))

    def test_servicios_basicos_no_se_clasifican_como_alquiler(self):
        a=novatech()[6];a['fuente']=SERVICIOS
        a['movimientos'][0].update(codigo='635',nombre='Alquileres')
        b=normalizar_borrador({'asientos':[a]},fuente=SERVICIOS)
        m=b['asientos'][0]['movimientos'][0]
        self.assertEqual((m['codigo'],m['nombre'],m['monto']),('636','Servicios básicos','1000'))

    def test_fragmento_no_literal_o_anticipo_no_se_invierte(self):
        for fuente,fragmento in [(PAGO,'La empresa paga S/ 4,000 de otra deuda.'),
                                 ('Se paga un anticipo al proveedor por S/ 4,000.','Se paga un anticipo al proveedor por S/ 4,000.')]:
            with self.subTest(fragmento=fragmento):
                a=novatech()[5];a['fuente']=fragmento
                for m in a['movimientos']:m['tipo_movimiento']='haber' if m['tipo_movimiento']=='debe' else 'debe'
                esperado=[m['tipo_movimiento'] for m in a['movimientos']]
                result=preparar_pcge([a],fuente)[0]
                self.assertEqual([m['tipo_movimiento'] for m in result['movimientos']],esperado)

    def test_pago_con_dos_importes_no_se_invierte_automaticamente(self):
        fuente='La empresa paga S/ 4,000 al proveedor y S/ 100 de intereses.'
        a=novatech()[5];a.update(fuente=fuente,descripcion='Pago a proveedor')
        for m in a['movimientos']:m['tipo_movimiento']='haber' if m['tipo_movimiento']=='debe' else 'debe'
        b=preparar_pcge([a],fuente)
        self.assertEqual(b[0]['movimientos'][0]['tipo_movimiento'],'haber')
        self.assertTrue(any('pago invertido' in n for n in auditar_asientos(b)))

    def test_multiples_subcategorias_no_se_ocultan(self):
        a=novatech()[6];a['fuente']=SERVICIOS
        a['movimientos'][0].update(codigo='635',nombre='Alquileres',subcategoria='gasto_operativo|gasto_financiero')
        b=normalizar_borrador({'asientos':[a]},fuente=SERVICIOS)
        self.assertTrue(b['asientos'][0]['error_validacion'])
