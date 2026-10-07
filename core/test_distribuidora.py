"""Regresión del ejercicio de Distribuidora Andina enviado en la fotografía."""
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from .ciclo_contable import generar_asientos
from .test_ciclo_contable import imagen
from .models import AsientoContable
from .reporte_utils import contexto_estados


def caso_andina():
    datos = {'empresa_nueva':True,'metodo_inventario':'periodico','inventario_inicial':None,
            'fecha_cierre':'2026-11-30','errores_lectura':[],'saldos_apertura':[],
            'operaciones':[
                {'fecha':'2026-11-02','tipo':'aporte_efectivo','monto':'40000'},
                {'fecha':'2026-11-03','tipo':'compra_mercaderia','monto':'18000','pago':'contado'},
                {'fecha':'2026-11-05','tipo':'compra_mercaderia','monto':'10000','pago':'credito'},
                {'fecha':'2026-11-08','tipo':'compra_activo','monto':'6000','pago':'contado','vida_util_anios':'10','residual_porcentaje':'0','fecha_inicio_uso':'2026-11-08'},
                {'fecha':'2026-11-10','tipo':'venta','monto':'35000','descuento_comercial_porcentaje':'10','monto_contado':'20000'},
                {'fecha':'2026-11-15','tipo':'pago_servicios','monto':'2500','detalles':[{'concepto':'alquiler','monto':'2500'}]},
                {'fecha':'2026-11-20','tipo':'cobro_factura','monto':'4000','fecha_factura':None},
                {'fecha':'2026-11-25','tipo':'pago_proveedor','monto':'6000'},
                {'fecha':'2026-11-28','tipo':'pago_servicios','monto':'800','detalles':[{'concepto':'servicios básicos','monto':'800'}]},
                {'fecha':'2026-11-30','tipo':'sueldos_mixtos','monto':'4000','monto_pagado':'3000','monto_pendiente':'1000'},
                {'fecha':'2026-11-30','tipo':'inventario_final','monto':'11000'}]}
    textos = [
        'Los socios aportan S/ 40,000 en efectivo para iniciar operaciones.',
        'Compra mercaderías por S/ 18,000 al contado.',
        'Compra mercaderías por S/ 10,000 a crédito con pago a 30 días.',
        'Compra equipo de cómputo por S/ 6,000 al contado; lo usa ese día. Vida útil 10 años, sin valor residual, depreciación del mes completo.',
        'Vende a precio de lista S/ 35,000 con descuento comercial del 10%. El cliente paga S/ 20,000 en efectivo; saldo por cobrar.',
        'Paga alquiler S/ 2,500 en efectivo.',
        'El cliente cancela S/ 4,000 de su deuda.',
        'Paga S/ 6,000 al proveedor por la compra a crédito.',
        'Paga servicios básicos S/ 800 en efectivo.',
        'Registra sueldos S/ 4,000: paga S/ 3,000 en efectivo y queda pendiente S/ 1,000.',
        'Inventario físico final S/ 11,000 al cierre del 30/11/2026.']
    for op,texto in zip(datos['operaciones'],textos):op['texto']=texto
    datos['texto_leido']='\n'.join(op['fecha']+': '+op['texto'] for op in datos['operaciones'])
    return datos


class DistribuidoraTests(TestCase):
    def test_operaciones_ajustes_y_balance_independientes_de_ia(self):
        asientos=generar_asientos(caso_andina())
        self.assertEqual(len(asientos),12)
        saldos={}
        for a in asientos:
            debe=sum(m['monto'] for m in a['movimientos'] if m['tipo_movimiento']=='debe')
            haber=sum(m['monto'] for m in a['movimientos'] if m['tipo_movimiento']=='haber')
            self.assertEqual(debe,haber)
            for m in a['movimientos']:
                saldos[m['codigo']]=saldos.get(m['codigo'],0)+m['monto']*(1 if m['tipo_movimiento']=='debe' else -1)
        self.assertEqual(saldos,{'10':27700,'12':7500,'20':11000,'33':6000,'39':-50,'41':-1000,'42':-4000,'50':-40000,'62':4000,'63':3300,'68':50,'69':17000,'70':-31500})
        with patch('core.ai_diario.extraer_operaciones',return_value=caso_andina()),patch('core.importacion_general.proponer_caso_general') as general:
            response=self.client.post(reverse('cargar_imagen_diario'),{'imagen_caso':imagen(),'revisar':'on'})
            general.assert_not_called()
        self.assertEqual(response.context['pendientes'],[])
        self.assertEqual(AsientoContable.objects.count(),0)
        token=response.context['revision_token']
        from django.core import signing
        import json
        payload=signing.loads(token,salt='revision-contable')
        self.client.post(reverse('revisar_importacion'),{'revision_token':token,'revisado':'on','asientos_json':json.dumps(payload['borrador']['asientos'])})
        estados=contexto_estados()
        self.assertEqual(estados['total_activos'],Decimal('52150'))
        self.assertEqual(estados['utilidad_antes_impuesto'],Decimal('7150'))

    def test_aporte_duplicado_como_apertura_no_se_registra_dos_veces(self):
        datos=caso_andina()
        datos['saldos_apertura']=[{'concepto':'caja','monto':'40000'},{'concepto':'capital','monto':'40000'}]
        self.assertEqual(generar_asientos(datos),generar_asientos(caso_andina()))
        datos['saldos_apertura'][0]['monto']='41000'
        with self.assertRaises(ValueError):generar_asientos(datos)

    def test_reglas_recalculan_otros_importes_y_porcentajes(self):
        datos=caso_andina()
        datos['operaciones'][0]['monto']='50000'
        datos['operaciones'][2]['monto']='12000'
        datos['operaciones'][4].update(monto='40000',descuento_comercial_porcentaje='5',monto_contado='25000')
        datos['operaciones'][9].update(monto='5500',monto_pagado='4000',monto_pendiente='1500')
        datos['operaciones'][10]['monto']='13000'
        asientos=generar_asientos(datos)
        saldos={}
        for a in asientos:
            for m in a['movimientos']:
                saldos[m['codigo']]=saldos.get(m['codigo'],0)+m['monto']*(1 if m['tipo_movimiento']=='debe' else -1)
        self.assertEqual(saldos['10'],41700)
        self.assertEqual(saldos['12'],9000)
        self.assertEqual(saldos['42'],-6000)
        self.assertEqual(saldos['41'],-1500)
        self.assertEqual(saldos['70'],-38000)
        self.assertEqual(saldos['69'],17000)

    def test_importes_inconsistentes_y_referencias_ambiguas_se_rechazan(self):
        cambios=[lambda d:d['operaciones'][4].update(monto_contado='32000'),
                 lambda d:d['operaciones'][7].update(monto='10001'),
                 lambda d:d['operaciones'][9].update(monto_pendiente='1500'),
                 lambda d:d['operaciones'].insert(6,{'fecha':'2026-11-19','tipo':'venta','monto':'1000','porcentaje_contado':'0','texto':'Una segunda venta a crédito por S/ 1000.'})]
        for cambio in cambios:
            datos=deepcopy(caso_andina());cambio(datos)
            with self.assertRaises(ValueError):generar_asientos(datos)
