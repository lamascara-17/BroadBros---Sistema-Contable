from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from .ciclo_contable import generar_asientos
from .models import AsientoContable


def caso_servicios():
    operaciones=[
        {'fecha':'2025-10-01','tipo':'aporte_efectivo','monto':'30000','texto':'Socios aportan 30000 en efectivo.'},
        {'fecha':'2025-10-05','tipo':'compra_activo','monto':'12000','pago':'mixto','monto_pagado':'5000','monto_pendiente':'7000','texto':'Equipos por 12000, paga 5000 en efectivo y debe 7000.'},
        {'fecha':'2025-10-10','tipo':'ingreso_servicios','monto':'15000','monto_contado':'9000','monto_pendiente':'6000','texto':'Consultoría por 15000; cobra 9000 y queda 6000 por cobrar.'},
        {'fecha':'2025-10-15','tipo':'pago_servicios','monto':'3000','detalles':[{'concepto':'alquiler','monto':'3000'}],'texto':'Paga alquiler 3000 en efectivo.'},
        {'fecha':'2025-10-22','tipo':'cobro_factura','monto':'3000','texto':'Cliente cancela 3000 de su deuda.'},
        {'fecha':'2025-10-26','tipo':'pago_proveedor','monto':'4000','texto':'Paga al proveedor 4000 por los equipos.'},
        {'fecha':'2025-10-30','tipo':'pago_servicios','monto':'1000','detalles':[{'concepto':'servicios básicos','monto':'1000'}],'texto':'Paga servicios básicos 1000 en efectivo.'}]
    return {'empresa_nueva':True,'metodo_inventario':'sin_inventario','inventario_inicial':None,'saldos_apertura':[],
            'fecha_cierre':'2025-10-30','errores_lectura':[],'operaciones':operaciones,
            'texto_leido':'\n'.join(op['fecha']+' '+op['texto'] for op in operaciones)}


def saldos(asientos):
    resultado={}
    for a in asientos:
        for m in a['movimientos']:
            resultado[m['codigo']]=resultado.get(m['codigo'],0)+m['monto']*(1 if m['tipo_movimiento']=='debe' else -1)
    return resultado


class ServiciosTests(TestCase):
    def test_siete_operaciones_y_pago_inicial_de_equipos(self):
        asientos=generar_asientos(caso_servicios())
        self.assertEqual(len(asientos),7)
        self.assertEqual(saldos(asientos),{'10':29000,'50':-30000,'33':12000,'42':-3000,'12':3000,'70':-15000,'63':4000})
        caja=[m for a in asientos for m in a['movimientos'] if m['codigo']=='10']
        self.assertEqual(sum(m['monto'] for m in caja if m['tipo_movimiento']=='debe'),42000)
        self.assertEqual(sum(m['monto'] for m in caja if m['tipo_movimiento']=='haber'),13000)

    def test_texto_e_imagen_comparten_calculo_sin_propuesta_general(self):
        from .test_ciclo_contable import imagen
        for ruta,lector,post in [('cargar_texto_diario','extraer_operaciones_texto',{'texto_caso':caso_servicios()['texto_leido']}),
                                  ('cargar_imagen_diario','extraer_operaciones',{'imagen_caso':imagen(),'revisar':'on'})]:
            with self.subTest(ruta=ruta),patch('core.ai_diario.'+lector,return_value=caso_servicios()),patch('core.importacion_general.proponer_caso_general') as general:
                response=self.client.post(reverse(ruta),post)
                general.assert_not_called()
                self.assertEqual(response.status_code,200)
                self.assertEqual(len(response.context['asientos']),7)
        self.assertEqual(AsientoContable.objects.count(),0)

    def test_recalcula_otros_pagos_y_rechaza_saldos_incompatibles(self):
        datos=caso_servicios()
        datos['operaciones'][1].update(monto_pagado='6000',monto_pendiente='6000')
        self.assertEqual(saldos(generar_asientos(datos))['10'],28000)
        datos['operaciones'][1]['monto_pendiente']='7000'
        with self.assertRaises(ValueError):generar_asientos(datos)
        datos=caso_servicios();datos['operaciones'][1].pop('monto_pagado')
        with self.assertRaises(ValueError):generar_asientos(datos)

    def test_servicios_no_eliminan_exigencia_de_cierre_para_mercaderias(self):
        datos=caso_servicios();datos['operaciones'][2]['tipo']='venta'
        with self.assertRaises(ValueError):generar_asientos(datos)
