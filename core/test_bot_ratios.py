from unittest.mock import patch
from django.test import SimpleTestCase
from django.urls import reverse
from .test_support import AdministrativeTestCase
from .test_estados_financieros import novatech
from .views import guardar_importacion
from .bot_ratios import respuesta_ratios_caso, indicador_consultado
from .ratios import DEFINITIONS
from .models import Movimiento


class SeleccionRatioTests(SimpleTestCase):
    def test_los_17_nombres_se_reconocen_sin_confundir_coberturas(self):
        for key,nombre,*_ in DEFINITIONS:
            with self.subTest(key=key):self.assertEqual(indicador_consultado('Explícame '+nombre),key)
        self.assertEqual(indicador_consultado('deuda financiera / EBITDA'),'debt_cover')
        self.assertEqual(indicador_consultado('margen EBITDA'),'ebitda_margin')
        self.assertEqual(indicador_consultado('cuánto debo pagar al proveedor'),'')

    def test_externo_responde_los_17_con_el_valor_visible_y_sin_parrafos_largos(self):
        from decimal import Decimal
        from .test_ratio_lab import example
        from .ratio_lab import explanations,tutor
        report=example();details=explanations(report,Decimal('.3'),'total')
        for key,nombre,*_ in DEFINITIONS:
            with self.subTest(key=key):
                answer,metric=tutor(report,details,'Explica '+nombre)
                self.assertEqual(metric,key)
                self.assertIn(details[key]['value'],answer)
                self.assertNotIn('Sustitución:',answer)
                self.assertLess(len(answer.split()),115)
        answer,_=tutor(report,details,'Cómo se calcula el margen neto paso a paso')
        self.assertIn('Sustitución:',answer)


class BotRatiosTests(AdministrativeTestCase):
    def test_valor_real_ejemplo_por_100_y_sin_api(self):
        guardar_importacion(novatech())
        with patch('core.views.Groq') as api:
            response=self.client.post(reverse('chatbot_api'),{'message':'Explícame el margen neto de mi caso'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'calculated');api.assert_not_called()
        answer=response.json()['response']
        self.assertIn('73.33%',answer);self.assertIn('S/ 73.33',answer)
        self.assertLess(len(answer.split()),90)
        self.assertIsInstance(response.json()['segments'],list)

    def test_no_hay_datos_no_inventa_ejemplo_ni_cero(self):
        answer=respuesta_ratios_caso('Explica la liquidez corriente')
        self.assertIn('N/D',answer);self.assertNotIn('S/ 0.00',answer)
        self.assertIn('N/D no significa cero',answer)

    def test_los_valores_cambian_al_editar_el_caso(self):
        guardar_importacion(novatech())
        first=respuesta_ratios_caso('margen neto')
        gasto=Movimiento.objects.filter(cuenta__tipo='gasto',monto=1000).get()
        gasto.monto=2000;gasto.save()
        pago=Movimiento.objects.get(asiento=gasto.asiento,tipo='haber')
        pago.monto=2000;pago.save()
        second=respuesta_ratios_caso('margen neto')
        self.assertNotEqual(first,second)
        self.assertIn('66.67%',second)

    def test_formula_solo_a_peticion_y_sin_mezclar_empresas(self):
        guardar_importacion(novatech())
        self.assertNotIn('Fórmula:',respuesta_ratios_caso('liquidez corriente'))
        self.assertIn('Fórmula:',respuesta_ratios_caso('cómo se calcula la liquidez corriente'))
        self.assertIsNone(respuesta_ratios_caso('margen neto de Broadcom'))

    def test_sugerencias_del_caso_y_resumen_corto(self):
        page=self.client.get(reverse('ratios_caso'))
        self.assertContains(page,'Mi liquidez');self.assertContains(page,'Mi rentabilidad')
        answer=respuesta_ratios_caso('Resume los ratios de mi caso')
        self.assertLess(len(answer.split()),90)
        self.assertEqual(answer.count('•'),3)
