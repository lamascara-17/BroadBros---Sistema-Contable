from io import BytesIO
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook
from .views import guardar_importacion
from .reporte_utils import contexto_estados
from .models import AsientoContable
from .importacion_general import normalizar_borrador
from .orientacion import orientar_revision


CATALOGO={'101':('Caja','activo',''),'1041':('Banco','activo',''),'121':('Clientes','activo',''),
          '336':('Equipos de cómputo','activo',''),'465':('Proveedor de equipos','pasivo',''),
          '50':('Capital','patrimonio',''),'59':('Resultados acumulados','patrimonio',''),
          '63':('Alquiler y servicios','gasto','gasto_operativo'),'704':('Consultoría','ingreso',''),
          '87':('Impuesto a las ganancias','gasto','impuesto_ganancias'),'4017':('Renta por pagar','pasivo','')}
CATALOGO.update({'79':('Cargas imputables a costos','ingreso',''),'94':('Gastos de administración','gasto','gasto_operativo'),
                 '77':('Ingresos financieros','ingreso','')})


def asiento(dia,descripcion,lineas,clase='operacion',flujo='pendiente'):
    movimientos=[]
    for codigo,lado,monto in lineas:
        nombre,tipo,sub=CATALOGO[codigo]
        movimientos.append({'codigo':codigo,'nombre':nombre,'tipo_cuenta':tipo,'subcategoria':sub,'tipo_movimiento':lado,'monto':str(monto)})
    return {'fecha':f'2025-10-{dia:02}','descripcion':descripcion,'clase':clase,'flujo_efectivo':flujo,'movimientos':movimientos}


def novatech():
    return [asiento(1,'Aporte inicial',[('101','debe',30000),('50','haber',30000)],flujo='financiacion'),
            asiento(5,'Compra de equipos, pago parcial',[('336','debe',12000),('101','haber',5000),('465','haber',7000)],flujo='inversion'),
            asiento(10,'Servicios de consultoría',[('101','debe',9000),('121','debe',6000),('704','haber',15000)],flujo='operacion'),
            asiento(15,'Alquiler',[('63','debe',3000),('101','haber',3000)],flujo='operacion'),
            asiento(22,'Cobro parcial',[('101','debe',3000),('121','haber',3000)],flujo='operacion'),
            asiento(26,'Pago parcial de equipos',[('465','debe',4000),('101','haber',4000)],flujo='inversion'),
            asiento(30,'Servicios básicos',[('63','debe',1000),('101','haber',1000)],flujo='operacion')]


class EstadosFinancierosTests(TestCase):
    def test_destino_no_duplica_gasto_y_intereses_no_son_ventas(self):
        guardar_importacion(novatech()+[asiento(30,'Destino de gastos',[('94','debe',4000),('79','haber',4000)]),
                                      asiento(30,'Intereses cobrados',[('101','debe',100),('77','haber',100)],flujo='operacion')],False)
        ctx=contexto_estados()
        self.assertEqual(ctx['total_gastos_operativos'],4000)
        self.assertEqual(ctx['total_ventas'],15000)
        self.assertEqual(ctx['total_otros_ingresos'],100)
        self.assertEqual(ctx['resultado_neto'],11100)
        self.assertTrue(ctx['esta_balanceado'])

    def test_novatech_reconcilia_libros_resultado_patrimonio_y_efectivo(self):
        guardar_importacion(novatech(),False)
        with self.assertNumQueries(4):ctx=contexto_estados()
        self.assertEqual(ctx['resultado_neto'],11000)
        self.assertEqual(ctx['total_activos'],44000)
        self.assertEqual(ctx['total_pasivos'],3000)
        self.assertEqual(ctx['total_patrimonio_con_resultados'],41000)
        self.assertEqual(ctx['totales_patrimonio']['final'],41000)
        self.assertEqual([r[1] for r in ctx['filas_flujos'][:3]],[8000,-9000,30000])
        self.assertEqual(ctx['filas_flujos'][-1][1],29000)
        self.assertEqual(ctx['gran_total_debe'],68000)
        self.assertEqual(ctx['gran_total_haber'],68000)
        self.assertTrue(ctx['esta_balanceado'])
        for ruta in ('libro_diario','libro_mayor','balance_comprobacion','estado_resultados','balance_general'):
            self.assertEqual(self.client.get(reverse(ruta)).status_code,200)

    def test_cierre_no_borra_utilidad_ni_duplica_patrimonio(self):
        entradas=novatech()+[asiento(31,'Cierre de resultados',[('704','debe',15000),('63','haber',4000),('59','haber',11000)],clase='cierre')]
        guardar_importacion(entradas,False)
        ctx=contexto_estados()
        self.assertEqual(ctx['resultado_neto'],11000)
        self.assertEqual(ctx['resultados_acumulados'],0)
        self.assertEqual(ctx['total_patrimonio_con_resultados'],41000)
        self.assertEqual(ctx['totales_patrimonio']['resultado'],11000)
        self.assertTrue(ctx['esta_balanceado'])

    def test_impuesto_registrado_y_perdida_con_signo_correcto(self):
        guardar_importacion(novatech()+[asiento(31,'Impuesto del ejercicio',[('87','debe',3000),('4017','haber',3000)])],False)
        ctx=contexto_estados()
        self.assertEqual(ctx['utilidad_antes_impuesto'],11000)
        self.assertEqual(ctx['resultado_neto'],8000)
        self.assertEqual(ctx['total_patrimonio_con_resultados'],38000)
        self.assertTrue(ctx['esta_balanceado'])
        entradas=novatech();entradas[3]['movimientos'][0]['monto']='23000';entradas[3]['movimientos'][1]['monto']='23000'
        guardar_importacion(entradas,True)
        self.assertEqual(contexto_estados()['resultado_neto'],-9000)

    def test_apertura_e_ingreso_historico_no_se_tratan_como_flujo_del_periodo(self):
        guardar_importacion([asiento(1,'Saldo anterior',[('101','debe',10000),('50','haber',10000)],clase='apertura'),
                             asiento(2,'Transferencia a banco',[('1041','debe',5000),('101','haber',5000)])],False)
        ctx=contexto_estados()
        self.assertEqual(ctx['filas_flujos'][-2][1],10000)
        self.assertEqual(ctx['filas_flujos'][-3][1],0)
        self.assertEqual(ctx['totales_patrimonio']['inicial'],10000)
        self.assertEqual(ctx['resultado_neto'],0)

    def test_flujo_ambiguo_se_identifica_incluso_si_su_neto_es_cero(self):
        entradas=novatech()
        entradas[5]['flujo_efectivo']='pendiente'
        guardar_importacion(entradas,False)
        ctx=contexto_estados()
        self.assertEqual(len(ctx['pendientes_flujo']),1)
        self.assertIn('Flujos pendientes de clasificación',[r[0] for r in ctx['filas_flujos']])
        self.assertEqual(ctx['filas_flujos'][-1][1],29000)

    def test_exportacion_incluye_todos_los_estados_con_los_mismos_totales(self):
        guardar_importacion(novatech(),False)
        r=self.client.post(reverse('reporte_completo'),{'empresa':'NovaTech','formato':'excel','accion':'descargar'})
        wb=load_workbook(BytesIO(r.content),data_only=True)
        self.assertEqual(wb.sheetnames, ['Situación Financiera', 'Estado de Resultados', 'Libro Diario', 'Libro Mayor', 'Balance Comprobación'])
        for path in ('/reportes/cambios-patrimonio/', '/reportes/flujos-efectivo/'):
            self.assertEqual(self.client.get(path).status_code, 404)
        pagina = self.client.get(reverse('balance_general')).content.decode()
        self.assertNotIn('Cambios en el patrimonio', pagina)
        self.assertNotIn('Flujos de efectivo', pagina)

    def test_nono_bot_detecta_omision_y_da_preguntas_del_analisis(self):
        borrador=normalizar_borrador({'asientos':novatech()[:1],'pendientes':['Falta la vida útil para calcular depreciación.']})
        datos={'texto_leido':'El día 01 de octubre de 2025 aporta 30000. El día 05 de octubre de 2025 compra equipos por 12000.'}
        pendientes,sugerencias=orientar_revision(datos,borrador)
        self.assertTrue(any('2025-10-05' in p for p in pendientes))
        self.assertIn('Falta la vida útil para calcular depreciación.',sugerencias)
        with patch('core.importacion_general.proponer_caso_general',return_value=borrador):
            r=self.client.post(reverse('cargar_texto_diario'),{'texto_caso':datos['texto_leido']})
        self.assertContains(r,'ÑoñoBot te orienta')
        self.assertContains(r,'2025-10-05')
        self.assertEqual(AsientoContable.objects.count(),0)
