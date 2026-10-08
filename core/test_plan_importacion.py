from copy import deepcopy
from unittest.mock import patch
from django.test import TestCase
from .models import CuentaContable, AsientoContable, Movimiento
from .test_estados_financieros import novatech
from .views import guardar_importacion
from .reporte_utils import contexto_estados


class PlanImportacionTests(TestCase):
    def test_cada_caso_reemplaza_asientos_y_crea_cuentas_nuevas(self):
        guardar_importacion(novatech(), False)
        anteriores = set(CuentaContable.objects.values_list('pk', flat=True))
        CuentaContable.objects.create(codigo='999', nombre='Cuenta anterior sin uso', tipo='activo')
        nuevos = deepcopy(novatech())
        for a in nuevos:
            for m in a['movimientos']:
                m['codigo'] = '9' + m['codigo']
        guardar_importacion(nuevos, False)
        self.assertFalse(anteriores & set(CuentaContable.objects.values_list('pk', flat=True)))
        self.assertFalse(CuentaContable.objects.filter(codigo='999').exists())
        self.assertFalse(CuentaContable.objects.filter(codigo='101').exists())
        self.assertTrue(CuentaContable.objects.filter(codigo='9101').exists())
        self.assertEqual(AsientoContable.objects.count(), 7)
        self.assertEqual(contexto_estados()['mayor_datos'][0]['saldo_final'], 29000)

    def test_propuesta_invalida_conserva_el_caso_anterior(self):
        guardar_importacion(novatech(), False)
        ids = list(AsientoContable.objects.values_list('pk', flat=True))
        cuentas = list(CuentaContable.objects.values_list('pk', flat=True))
        nuevos = deepcopy(novatech())
        nuevos[0]['movimientos'][0]['monto'] = '30001'
        with self.assertRaises(ValueError): guardar_importacion(nuevos, False)
        self.assertEqual(list(AsientoContable.objects.values_list('pk', flat=True)), ids)
        self.assertEqual(list(CuentaContable.objects.values_list('pk', flat=True)), cuentas)

    def test_fallo_de_guardado_revierte_la_limpieza(self):
        guardar_importacion(novatech(), False)
        ids = list(AsientoContable.objects.values_list('pk', flat=True))
        cuentas = list(CuentaContable.objects.values_list('pk', flat=True))
        with patch.object(Movimiento.objects, 'bulk_create', side_effect=RuntimeError('Fallo de escritura')):
            with self.assertRaises(RuntimeError): guardar_importacion(novatech(), True)
        self.assertEqual(list(AsientoContable.objects.values_list('pk', flat=True)), ids)
        self.assertEqual(list(CuentaContable.objects.values_list('pk', flat=True)), cuentas)
