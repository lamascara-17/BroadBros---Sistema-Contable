"""Flujo académico de un solo caso, sin cuentas de usuario ni servicios extras."""
from unittest.mock import patch
from django.db import DatabaseError
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from .contexto_bot import firma_caso, guardar_conversacion
from .models import AsientoContable, CuentaContable, FinancialRatioPeriod, RespaldoCaso, Workspace
from .test_estados_financieros import novatech
from .test_respaldos_recursos import Visitantes
from .workspaces import actual


@override_settings(WORKSPACE_ISOLATION=True)
class FlujoAcademicoTests(Visitantes, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.sembrar(self.a)
        token = actual.set(self.a.session['workspace_id'])
        self.addCleanup(actual.reset, token)
        self.ruta = reverse('nuevo_caso')

    def conversar(self):
        firma = firma_caso()
        turnos = [{'usuario':'Mi caso', 'respuesta':'Datos del caso anterior'}]
        estado = Workspace.objects.get(pk=actual.get())
        self.assertTrue(guardar_conversacion(firma, estado.bot_sequence, turnos))
        sesion = self.a.session
        sesion['nonobot_caso'] = firma
        sesion['nonobot_turnos'] = turnos
        sesion.save()
        return firma, turnos

    def test_nuevo_caso_respalda_y_permite_restaurar_sin_tocar_ratios_externos(self):
        original = self.exportar(self.a).content
        workspace = self.a.session['workspace_id']
        externo = FinancialRatioPeriod.objects.create(ticker='AVGO', year=2025, name='Broadcom',
            period_start='2025-01-01', period_end='2025-12-31', previous_end='2024-12-31', values={})
        self.conversar()
        self.assertRedirects(self.a.post(self.ruta), reverse('index'))
        self.assertFalse(AsientoContable.objects.exists())
        self.assertFalse(CuentaContable.objects.exists())
        self.assertTrue(FinancialRatioPeriod.objects.filter(pk=externo.pk).exists())
        self.assertEqual(self.a.session['workspace_id'], workspace)
        self.assertNotIn('nonobot_turnos', self.a.session)
        respaldo = RespaldoCaso.objects.get()
        self.a.post(reverse('restaurar_respaldo', args=[respaldo.pk]))
        self.assertEqual(self.exportar(self.a).content, original)

    def test_get_y_post_sin_csrf_no_vacian_el_caso(self):
        original = self.exportar(self.a).content
        self.assertEqual(self.a.get(self.ruta).status_code, 405)
        seguro = Client(enforce_csrf_checks=True)
        seguro.cookies = self.a.cookies
        self.assertEqual(seguro.post(self.ruta).status_code, 403)
        self.assertEqual(self.exportar(self.a).content, original)
        self.assertEqual(RespaldoCaso.objects.count(), 0)

    def test_respaldo_fallido_conserva_caso_revision_y_conversacion(self):
        original = self.exportar(self.a).content
        firma, turnos = self.conversar()
        with patch('core.respaldos.crear_respaldo', side_effect=ValueError('No se pudo crear la copia')):
            self.assertEqual(self.a.post(self.ruta).status_code, 302)
        self.assertEqual(self.exportar(self.a).content, original)
        self.assertEqual(firma_caso(), firma)
        self.assertEqual(self.a.session['nonobot_turnos'], turnos)
        self.assertEqual(Workspace.objects.get(pk=actual.get()).bot_turnos, turnos)

    def test_fallo_despues_de_borrar_asientos_revierte_todo(self):
        original = self.exportar(self.a).content
        firma, turnos = self.conversar()
        def fallar():
            self.assertEqual(AsientoContable.objects.count(), 0)
            self.assertEqual(RespaldoCaso.objects.count(), 1)
            raise DatabaseError('Fallo de prueba después del borrado')
        with patch('core.models.CuentaContable.objects.all') as cuentas:
            cuentas.return_value.delete.side_effect = fallar
            self.assertEqual(self.a.post(self.ruta).status_code, 302)
        self.assertEqual(self.exportar(self.a).content, original)
        self.assertEqual(firma_caso(), firma)
        self.assertEqual(RespaldoCaso.objects.count(), 0)
        self.assertEqual(self.a.session['nonobot_turnos'], turnos)

    def test_nuevo_caso_vacio_limpia_contexto_e_invalida_respuesta_tardia(self):
        self.a.post(self.ruta)
        firma, _ = self.conversar()
        secuencia = Workspace.objects.get(pk=actual.get()).bot_sequence
        copias = RespaldoCaso.objects.count()
        self.a.post(self.ruta)
        self.assertNotEqual(firma_caso(), firma)
        self.assertEqual(Workspace.objects.get(pk=actual.get()).bot_turnos, [])
        self.assertFalse(guardar_conversacion(firma, secuencia, [{'usuario':'Vieja', 'respuesta':'Vieja'}]))
        self.assertEqual(RespaldoCaso.objects.count(), copias)
        self.assertNotIn('nonobot_turnos', self.a.session)

    def test_nuevo_caso_no_afecta_a_otro_visitante(self):
        self.sembrar(self.b, novatech()[:1])
        ajeno = self.exportar(self.b).content
        self.a.post(self.ruta, {'workspace_id':self.b.session['workspace_id']})
        self.assertFalse(AsientoContable.objects.exists())
        self.assertEqual(self.exportar(self.b).content, ajeno)
        respaldo = RespaldoCaso.objects.get()
        self.assertEqual(self.b.get(reverse('descargar_respaldo', args=[respaldo.pk])).status_code, 404)

    def test_falta_de_ambito_no_permite_borrado_global(self):
        original = self.exportar(self.a).content
        token = actual.set(None)
        try:
            with override_settings(WORKSPACE_ISOLATION=False):
                self.assertEqual(self.a.post(self.ruta).status_code, 400)
        finally:
            actual.reset(token)
        self.assertEqual(self.exportar(self.a).content, original)
