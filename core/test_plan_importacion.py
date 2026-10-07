from copy import deepcopy
from django.test import TestCase
from .models import CuentaContable, AsientoContable
from .test_estados_financieros import novatech
from .views import guardar_importacion
from .reporte_utils import contexto_estados


class PlanImportacionTests(TestCase):
    def test_reimportar_con_codigos_distintos_conserva_plan_y_saldos(self):
        guardar_importacion(novatech(), False)
        plan = list(CuentaContable.objects.values_list('codigo', 'nombre', 'tipo'))
        nuevos = deepcopy(novatech())
        for a in nuevos:
            for m in a['movimientos']:
                m['codigo'] = '9' + m['codigo']
                if m['nombre'] == 'Caja': m['nombre'] = 'Efectivo en caja'
                if m['nombre'] == 'Capital': m['nombre'] = 'Capital social'
        guardar_importacion(nuevos, True)
        self.assertEqual(list(CuentaContable.objects.values_list('codigo', 'nombre', 'tipo')), plan)
        self.assertEqual(AsientoContable.objects.count(), 7)
        self.assertEqual(contexto_estados()['mayor_datos'][0]['saldo_final'], 29000)

    def test_colision_no_sobrescribe_ni_borra_movimientos(self):
        guardar_importacion(novatech(), False)
        nuevos = deepcopy(novatech())
        nuevos[0]['movimientos'][0]['nombre'] = 'Banco'
        ids = list(AsientoContable.objects.values_list('id', flat=True))
        with self.assertRaisesMessage(ValueError, 'ya pertenece a Caja'):
            guardar_importacion(nuevos, True)
        self.assertEqual(list(AsientoContable.objects.values_list('id', flat=True)), ids)
        self.assertEqual(CuentaContable.objects.get(codigo='101').nombre, 'Caja')

    def test_cuenta_nueva_se_crea_y_se_reutiliza(self):
        nuevos = novatech()[:1]
        guardar_importacion(nuevos, False)
        nuevos[0]['movimientos'][0]['codigo'] = '111'
        guardar_importacion(nuevos, False)
        self.assertEqual(CuentaContable.objects.filter(nombre='Caja').count(), 1)
        self.assertFalse(CuentaContable.objects.filter(codigo='111').exists())
