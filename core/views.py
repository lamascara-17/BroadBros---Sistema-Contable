"""
Vistas del Sistema Contable BroadBros - PC2 UNI.
"""
import os
import gc
import json
import base64
from decimal import Decimal, InvalidOperation
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from xhtml2pdf import pisa
from groq import Groq
from django.conf import settings
import groq
from django.db import transaction
from .models import CuentaContable, AsientoContable, Movimiento
from .reporte_utils import get_reporte_context

# Clave de Groq obtenida desde las variables de entorno
DEFAULT_GROQ_KEY = os.getenv("GROQ_API_KEY")


# ─── PÁGINA PRINCIPAL ──────────────────────────────────────────────────────────

def index(request):
    """
    Muestra el menú principal con un resumen del estado del sistema:
    total de cuentas, asientos, y totales de Debe/Haber.
    """
    total_asientos = AsientoContable.objects.count()
    total_cuentas = CuentaContable.objects.count()
    total_movimientos = Movimiento.objects.count()

    total_debe = Movimiento.objects.filter(tipo='debe').aggregate(
        total=Sum('monto'))['total'] or Decimal('0')
    total_haber = Movimiento.objects.filter(tipo='haber').aggregate(
        total=Sum('monto'))['total'] or Decimal('0')

    ultimos_asientos = AsientoContable.objects.prefetch_related(
        'movimientos__cuenta'
    ).order_by('-created_at')[:5]

    context = {
        'total_asientos': total_asientos,
        'total_cuentas': total_cuentas,
        'total_movimientos': total_movimientos,
        'total_debe': total_debe,
        'total_haber': total_haber,
        'ultimos_asientos': ultimos_asientos,
    }
    return render(request, 'index.html', context)


# ─── GESTIÓN DE CUENTAS CONTABLES ──────────────────────────────────────────────

def gestionar_cuentas(request):
    if request.method == 'POST':
        codigo = request.POST.get('codigo', '').strip()
        nombre = request.POST.get('nombre', '').strip()
        tipo = request.POST.get('tipo', '').strip()
        subcategoria = request.POST.get('subcategoria', '').strip()

        errors = []
        if not codigo:
            errors.append('El código es obligatorio.')
        if not nombre:
            errors.append('El nombre es obligatorio.')
        if tipo not in dict(CuentaContable.TIPO_CHOICES):
            errors.append('El tipo de cuenta no es válido.')
        if CuentaContable.objects.filter(codigo=codigo).exists():
            errors.append(f'Ya existe una cuenta con el código "{codigo}".')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            CuentaContable.objects.create(
                codigo=codigo, nombre=nombre, tipo=tipo, subcategoria=subcategoria
            )
            messages.success(request, f'Cuenta "{codigo} - {nombre}" creada exitosamente.')
            return redirect('gestionar_cuentas')

    cuentas = CuentaContable.objects.all()
    context = {
        'cuentas': cuentas,
        'tipos': CuentaContable.TIPO_CHOICES,
        'subcategorias': CuentaContable.SUBCATEGORIA_CHOICES,
    }
    return render(request, 'gestionar_cuentas.html', context)


def eliminar_cuenta(request, cuenta_id):
    cuenta = get_object_or_404(CuentaContable, id=cuenta_id)
    if cuenta.movimientos.exists():
        messages.error(
            request,
            f'No se puede eliminar "{cuenta}" porque tiene movimientos asociados.'
        )
    else:
        messages.success(request, f'Cuenta "{cuenta}" eliminada exitosamente.')
        cuenta.delete()
    return redirect('gestionar_cuentas')


# ─── REGISTRO MANUAL DE ASIENTOS ───────────────────────────────────────────────

def registrar_asiento(request):
    cuentas = CuentaContable.objects.all()

    if not cuentas.exists():
        messages.warning(
            request,
            'Debe crear al menos una cuenta contable antes de registrar asientos.'
        )
        return redirect('gestionar_cuentas')

    if request.method == 'POST':
        fecha = request.POST.get('fecha', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        num_movimientos = int(request.POST.get('num_movimientos', 0))

        errors = []
        if not fecha:
            errors.append('La fecha es obligatoria.')

        if num_movimientos < 2:
            errors.append('Debe registrar al menos 2 movimientos por asiento.')

        movimientos_data = []
        for i in range(num_movimientos):
            cuenta_id = request.POST.get(f'cuenta_{i}', '').strip()
            tipo = request.POST.get(f'tipo_{i}', '').strip()
            monto_str = request.POST.get(f'monto_{i}', '').strip()

            if not cuenta_id or not tipo or not monto_str:
                errors.append(f'Línea {i+1}: Todos los campos son obligatorios.')
                continue

            try:
                monto = Decimal(monto_str)
                if monto <= 0:
                    errors.append(f'Línea {i+1}: El monto debe ser mayor a 0.')
                    continue
            except (InvalidOperation, ValueError):
                errors.append(f'Línea {i+1}: El monto ingresado no es válido.')
                continue

            if tipo not in ('debe', 'haber'):
                errors.append(f'Línea {i+1}: El tipo debe ser Debe o Haber.')
                continue

            try:
                cuenta = CuentaContable.objects.get(id=int(cuenta_id))
            except (CuentaContable.DoesNotExist, ValueError):
                errors.append(f'Línea {i+1}: La cuenta seleccionada no existe.')
                continue

            movimientos_data.append({
                'cuenta': cuenta,
                'tipo': tipo,
                'monto': monto,
            })

        if not errors and len(movimientos_data) >= 2:
            total_debe = sum(m['monto'] for m in movimientos_data if m['tipo'] == 'debe')
            total_haber = sum(m['monto'] for m in movimientos_data if m['tipo'] == 'haber')

            if total_debe != total_haber:
                errors.append(
                    f'El asiento no está balanceado. '
                    f'Debe: S/ {total_debe:,.2f} ≠ Haber: S/ {total_haber:,.2f}'
                )
        elif not errors:
            errors.append('Debe registrar al menos 2 movimientos válidos.')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            asiento = AsientoContable.objects.create(
                fecha=fecha,
                descripcion=descripcion,
            )
            for m in movimientos_data:
                Movimiento.objects.create(
                    asiento=asiento,
                    cuenta=m['cuenta'],
                    tipo=m['tipo'],
                    monto=m['monto'],
                )
            
            hora_real = timezone.localtime(timezone.now()).strftime("%d/%m/%Y a las %H:%M")
            messages.success(request, f'Asiento registrado exitosamente el {hora_real}.')
            return redirect('libro_diario')

    asientos_registrados = AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('-created_at')

    context = {
        'cuentas': cuentas,
        'asientos_registrados': asientos_registrados,
    }
    return render(request, 'registrar_asiento.html', context)


def editar_asiento(request, asiento_id):
    asiento = get_object_or_404(AsientoContable, id=asiento_id)
    if request.method == 'POST':
        asiento.fecha = request.POST.get('fecha')
        asiento.descripcion = request.POST.get('descripcion')
        asiento.save()
        
        asiento.movimientos.all().delete()
        num_movs = int(request.POST.get('num_movimientos', 0))
        for i in range(num_movs):
            cuenta_id = request.POST.get(f'cuenta_{i}')
            tipo = request.POST.get(f'tipo_{i}')
            monto = request.POST.get(f'monto_{i}')
            if cuenta_id and monto:
                Movimiento.objects.create(
                    asiento=asiento,
                    cuenta_id=cuenta_id,
                    tipo=tipo,
                    monto=monto
                )
        
        ahora = timezone.localtime(timezone.now()).strftime("%d/%m/%Y a las %H:%M")
        messages.success(request, f"Asiento actualizado exitosamente el {ahora}.")
    return redirect('libro_diario')


def eliminar_asiento(request, asiento_id):
    asiento = get_object_or_404(AsientoContable, id=asiento_id)
    asiento_num = asiento.id 
    asiento.delete()
    messages.success(request, f'El Asiento #{asiento_num} fue eliminado correctamente.')
    return redirect('libro_diario')


# ─── LIBRO DIARIO ──────────────────────────────────────────────────────────────

def libro_diario(request):
    asientos = AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('fecha', 'id')
    cuentas = CuentaContable.objects.all()
    context = {
        'asientos': asientos,
        'cuentas': cuentas,
    }
    return render(request, 'libro_diario.html', context)


# ─── LIBRO MAYOR ───────────────────────────────────────────────────────────────

def libro_mayor(request):
    cuentas = CuentaContable.objects.all()
    datos_cuentas = []
    for cuenta in cuentas:
        movimientos = cuenta.movimientos.select_related('asiento').order_by('asiento__fecha', 'asiento__id')
        if not movimientos.exists():
            continue

        total_debe = movimientos.filter(tipo='debe').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')
        total_haber = movimientos.filter(tipo='haber').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')

        if cuenta.naturaleza_deudora:
            saldo = total_debe - total_haber
        else:
            saldo = total_haber - total_debe

        datos_cuentas.append({
            'cuenta': cuenta,
            'movimientos': movimientos,
            'total_debe': total_debe,
            'total_haber': total_haber,
            'saldo': saldo,
        })

    context = {
        'datos_cuentas': datos_cuentas,
    }
    return render(request, 'libro_mayor.html', context)


# ─── BALANCE DE COMPROBACIÓN ───────────────────────────────────────────────────

def balance_comprobacion(request):
    cuentas = CuentaContable.objects.all()
    datos = []
    gran_total_debe = Decimal('0')
    gran_total_haber = Decimal('0')
    gran_saldo_deudor = Decimal('0')
    gran_saldo_acreedor = Decimal('0')

    for cuenta in cuentas:
        total_debe = cuenta.movimientos.filter(tipo='debe').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')
        total_haber = cuenta.movimientos.filter(tipo='haber').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')

        if total_debe == 0 and total_haber == 0:
            continue

        saldo = total_debe - total_haber
        saldo_deudor = saldo if saldo > 0 else Decimal('0')
        saldo_acreedor = abs(saldo) if saldo < 0 else Decimal('0')

        datos.append({
            'cuenta': cuenta,
            'total_debe': total_debe,
            'total_haber': total_haber,
            'saldo_deudor': saldo_deudor,
            'saldo_acreedor': saldo_acreedor,
        })

        gran_total_debe += total_debe
        gran_total_haber += total_haber
        gran_saldo_deudor += saldo_deudor
        gran_saldo_acreedor += saldo_acreedor

    context = {
        'datos': datos,
        'gran_total_debe': gran_total_debe,
        'gran_total_haber': gran_total_haber,
        'gran_saldo_deudor': gran_saldo_deudor,
        'gran_saldo_acreedor': gran_saldo_acreedor,
        'esta_cuadrado': gran_total_debe == gran_total_haber,
    }
    return render(request, 'balance_comprobacion.html', context)


# ─── ESTADO DE RESULTADOS ──────────────────────────────────────────────────────

def estado_resultados(request):
    def saldo_cuenta(cuenta):
        t_debe = cuenta.movimientos.filter(tipo='debe').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')
        t_haber = cuenta.movimientos.filter(tipo='haber').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')
        if cuenta.tipo == 'gasto':
            return t_debe - t_haber
        else:
            return t_haber - t_debe

    def obtener_items(queryset):
        items = []
        total = Decimal('0')
        for c in queryset:
            s = saldo_cuenta(c)
            if s != 0:
                items.append({'cuenta': c, 'saldo': s})
                total += s
        return items, total

    ventas, total_ventas = obtener_items(
        CuentaContable.objects.filter(tipo='ingreso').exclude(subcategoria='otro_ingreso')
    )
    costo_ventas, total_costo_ventas = obtener_items(
        CuentaContable.objects.filter(tipo='gasto', subcategoria='costo_ventas')
    )
    utilidad_bruta = total_ventas - total_costo_ventas

    gastos_operativos, total_gastos_operativos = obtener_items(
        CuentaContable.objects.filter(tipo='gasto').exclude(
            subcategoria__in=['costo_ventas', 'gasto_financiero', 'otro_gasto']
        )
    )
    utilidad_operativa = utilidad_bruta - total_gastos_operativos

    gastos_financieros, total_gastos_financieros = obtener_items(
        CuentaContable.objects.filter(tipo='gasto', subcategoria='gasto_financiero')
    )
    otros_ingresos, total_otros_ingresos = obtener_items(
        CuentaContable.objects.filter(tipo='ingreso', subcategoria='otro_ingreso')
    )
    otros_gastos, total_otros_gastos = obtener_items(
        CuentaContable.objects.filter(tipo='gasto', subcategoria='otro_gasto')
    )

    utilidad_antes_impuesto = (
        utilidad_operativa
        - total_gastos_financieros
        + total_otros_ingresos
        - total_otros_gastos
    )

    tasa_impuesto = Decimal('30')
    if utilidad_antes_impuesto > 0:
        impuesto = (utilidad_antes_impuesto * tasa_impuesto / Decimal('100')).quantize(Decimal('0.01'))
    else:
        impuesto = Decimal('0')

    utilidad_neta = utilidad_antes_impuesto - impuesto

    context = {
        'ventas': ventas, 'total_ventas': total_ventas,
        'costo_ventas': costo_ventas, 'total_costo_ventas': total_costo_ventas,
        'utilidad_bruta': utilidad_bruta,
        'gastos_operativos': gastos_operativos, 'total_gastos_operativos': total_gastos_operativos,
        'utilidad_operativa': utilidad_operativa,
        'gastos_financieros': gastos_financieros, 'total_gastos_financieros': total_gastos_financieros,
        'otros_ingresos': otros_ingresos, 'total_otros_ingresos': total_otros_ingresos,
        'otros_gastos': otros_gastos, 'total_otros_gastos': total_otros_gastos,
        'utilidad_antes_impuesto': utilidad_antes_impuesto,
        'tasa_impuesto': tasa_impuesto,
        'impuesto': impuesto,
        'utilidad_neta': utilidad_neta,
    }
    return render(request, 'estado_resultados.html', context)


# ─── BALANCE GENERAL ───────────────────────────────────────────────────────────

def balance_general(request):
    def calcular_saldos_por_tipo(tipo_cuenta, deudora=True):
        cuentas = CuentaContable.objects.filter(tipo=tipo_cuenta)
        items = []
        total = Decimal('0')
        for cuenta in cuentas:
            t_debe = cuenta.movimientos.filter(tipo='debe').aggregate(
                total=Sum('monto'))['total'] or Decimal('0')
            t_haber = cuenta.movimientos.filter(tipo='haber').aggregate(
                total=Sum('monto'))['total'] or Decimal('0')
            saldo = (t_debe - t_haber) if deudora else (t_haber - t_debe)
            if saldo != 0:
                items.append({'cuenta': cuenta, 'saldo': saldo})
                total += saldo
        return items, total

    activos, total_activos = calcular_saldos_por_tipo('activo', deudora=True)
    pasivos, total_pasivos = calcular_saldos_por_tipo('pasivo', deudora=False)
    patrimonio, total_patrimonio = calcular_saldos_por_tipo('patrimonio', deudora=False)

    _, total_ingresos = calcular_saldos_por_tipo('ingreso', deudora=False)
    _, total_gastos = calcular_saldos_por_tipo('gasto', deudora=True)
    resultados_acumulados = total_ingresos - total_gastos  

    total_patrimonio_con_resultados = total_patrimonio + resultados_acumulados
    total_pasivo_patrimonio = total_pasivos + total_patrimonio_con_resultados
    esta_balanceado = total_activos == total_pasivo_patrimonio

    def totales_debe_haber(tipo_cuenta):
        cuentas = CuentaContable.objects.filter(tipo=tipo_cuenta)
        total_d = Decimal('0')
        total_h = Decimal('0')
        for c in cuentas:
            td = c.movimientos.filter(tipo='debe').aggregate(
                total=Sum('monto'))['total'] or Decimal('0')
            th = c.movimientos.filter(tipo='haber').aggregate(
                total=Sum('monto'))['total'] or Decimal('0')
            total_d += td
            total_h += th
        return total_d, total_h

    activo_debe, activo_haber = totales_debe_haber('activo')
    pasivo_debe, pasivo_haber = totales_debe_haber('pasivo')
    patrimonio_debe, patrimonio_haber = totales_debe_haber('patrimonio')

    ecuacion_resumen = [
        {
            'concepto': 'ACTIVO',
            'debe': activo_debe, 'haber': activo_haber,
            'saldo_deudor': activo_debe - activo_haber if activo_debe >= activo_haber else Decimal('0'),
            'saldo_acreedor': activo_haber - activo_debe if activo_haber > activo_debe else Decimal('0'),
        },
        {
            'concepto': 'PASIVO',
            'debe': pasivo_debe, 'haber': pasivo_haber,
            'saldo_deudor': pasivo_debe - pasivo_haber if pasivo_debe >= pasivo_haber else Decimal('0'),
            'saldo_acreedor': pasivo_haber - pasivo_debe if pasivo_haber > pasivo_debe else Decimal('0'),
        },
        {
            'concepto': 'PATRIMONIO',
            'debe': patrimonio_debe, 'haber': patrimonio_haber,
            'saldo_deudor': patrimonio_debe - patrimonio_haber if patrimonio_debe >= patrimonio_haber else Decimal('0'),
            'saldo_acreedor': patrimonio_haber - patrimonio_debe if patrimonio_haber > patrimonio_debe else Decimal('0'),
        },
    ]

    context = {
        'activos': activos, 'pasivos': pasivos, 'patrimonio': patrimonio,
        'total_activos': total_activos, 'total_pasivos': total_pasivos,
        'total_patrimonio': total_patrimonio, 'resultados_acumulados': resultados_acumulados,
        'es_utilidad': resultados_acumulados >= 0,
        'total_patrimonio_con_resultados': total_patrimonio_con_resultados,
        'total_pasivo_patrimonio': total_pasivo_patrimonio, 'esta_balanceado': esta_balanceado,
        'ecuacion_resumen': ecuacion_resumen,
        'ec_total_debe': sum(e['debe'] for e in ecuacion_resumen),
        'ec_total_haber': sum(e['haber'] for e in ecuacion_resumen),
        'ec_total_deudor': sum(e['saldo_deudor'] for e in ecuacion_resumen),
        'ec_total_acreedor': sum(e['saldo_acreedor'] for e in ecuacion_resumen),
    }
    return render(request, 'balance_general.html', context)


# ─── EXPORTACIÓN EN EXCEL Y REPORTE COMPLETO ──────────────────────────────────

def exportar_excel_contable(empresa="BroadBros"):
    """Genera un archivo Excel estructurado con Libro Diario y Balances."""
    wb = Workbook()
    ws_diario = wb.active
    ws_diario.title = "Libro Diario"

    header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    ws_diario.append([f"EMPRESA: {empresa} - LIBRO DIARIO"])
    ws_diario.append(["Fecha", "Asiento", "Código", "Cuenta", "Glosa / Descripción", "Debe (S/)", "Haber (S/)"])

    for cell in ws_diario[2]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center

    asientos = AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('fecha', 'id')
    row_idx = 3
    for a in asientos:
        for m in a.movimientos.all():
            debe = m.monto if m.tipo == 'debe' else Decimal('0.00')
            haber = m.monto if m.tipo == 'haber' else Decimal('0.00')
            ws_diario.append([
                str(a.fecha),
                f"Asiento #{a.id}",
                m.cuenta.codigo,
                m.cuenta.nombre,
                a.descripcion,
                float(debe),
                float(haber)
            ])
            ws_diario.cell(row=row_idx, column=6).alignment = align_right
            ws_diario.cell(row=row_idx, column=7).alignment = align_right
            row_idx += 1

    ws_balance = wb.create_sheet(title="Balance Comprobación")
    ws_balance.append([f"EMPRESA: {empresa} - BALANCE DE COMPROBACIÓN"])
    ws_balance.append(["Código", "Cuenta", "Suma Debe", "Suma Haber", "Saldo Deudor", "Saldo Acreedor"])

    for cell in ws_balance[2]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center

    cuentas = CuentaContable.objects.all().order_by('codigo')
    b_row = 3
    for c in cuentas:
        t_debe = c.movimientos.filter(tipo='debe').aggregate(total=Sum('monto'))['total'] or Decimal('0')
        t_haber = c.movimientos.filter(tipo='haber').aggregate(total=Sum('monto'))['total'] or Decimal('0')
        if t_debe == 0 and t_haber == 0:
            continue
        saldo = t_debe - t_haber
        s_deudor = saldo if saldo > 0 else Decimal('0')
        s_acreedor = abs(saldo) if saldo < 0 else Decimal('0')
        ws_balance.append([
            c.codigo, c.nombre, float(t_debe), float(t_haber), float(s_deudor), float(s_acreedor)
        ])
        for col_i in range(3, 7):
            ws_balance.cell(row=b_row, column=col_i).alignment = align_right
        b_row += 1

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream.getvalue()


def reporte_completo(request):
    """
    Permite descargar directamente el reporte en PDF, en Excel (.xlsx)
    o enviarlo al correo opcionalmente sin bloquearse por fallos SMTP.
    """
    if request.method == 'POST':
        empresa = request.POST.get('empresa', 'BroadBros').strip() or 'BroadBros'
        formato = request.POST.get('formato', 'pdf')
        correo = request.POST.get('correo', '').strip()

        # ── 1. Descarga directa en Excel ──
        if formato == 'excel':
            excel_data = exportar_excel_contable(empresa)
            response = HttpResponse(
                excel_data,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="Reporte_Contable_{empresa}.xlsx"'
            return response

        # ── 2. Generación de PDF en memoria ──
        gc.collect()
        context = get_reporte_context()
        context['empresa'] = empresa
        
        try:
            logo_path = os.path.join(settings.BASE_DIR, 'UNILOGO.png')
            with open(logo_path, "rb") as image_file:
                context['logo_base64'] = f"data:image/png;base64,{base64.b64encode(image_file.read()).decode('utf-8')}"
        except Exception:
            context['logo_base64'] = ""

        html = render_to_string('reporte_pdf.html', context)
        del context

        pdf_file = BytesIO()
        pisa_status = pisa.CreatePDF(BytesIO(html.encode('UTF-8')), dest=pdf_file)
        del html
        gc.collect()

        if pisa_status.err:
            messages.error(request, 'Error al generar PDF.')
            return redirect('reporte_completo')

        pdf_data = pdf_file.getvalue()

        # ── 3. Envío opcional por correo ──
        if correo and request.POST.get('accion') == 'enviar_correo':
            try:
                email = EmailMessage(
                    subject=f'Reporte Contable - {empresa}',
                    body=f'Reporte generado el {timezone.localtime(timezone.now()).strftime("%d/%m/%Y")}.',
                    from_email=getattr(settings, 'EMAIL_HOST_USER', 'webmaster@localhost'),
                    to=[correo]
                )
                email.attach(f'Reporte_{empresa}.pdf', pdf_data, 'application/pdf')
                email.send(fail_silently=False)
                messages.success(request, '¡Reporte enviado con éxito!')
                return redirect('reporte_completo')
            except Exception as e:
                messages.error(request, f'No se pudo enviar el correo: {str(e)}. Te recomendamos descargarlo directamente.')
                return redirect('reporte_completo')
            finally:
                pdf_file.close()

        # ── 4. Descarga directa en PDF por defecto ──
        response = HttpResponse(pdf_data, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Reporte_Contable_{empresa}.pdf"'
        return response

    return render(request, 'menu_reporte.html')


# ─── TUTOR EXPLICATIVO DEL LIBRO DIARIO (GROQ OFICIAL) ─────────────────────────

def chatbot_api(request):
    """
    Chatbot Tutor Contable: Explica técnicamente la dinámica del Libro Diario
    basado en los asientos reales registrados en la base de datos usando Groq.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    user_message = request.POST.get('message', '').strip()
    if not user_message:
        return JsonResponse({'error': 'Mensaje vacío'}, status=400)

    try:
        api_key = getattr(settings, 'GROQ_API_KEY', None) or os.environ.get('GROQ_API_KEY') or DEFAULT_GROQ_KEY

        asientos = AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('fecha', 'id')
        resumen_diario = []
        for a in asientos:
            movs = [f"Cuenta {m.cuenta.codigo} - {m.cuenta.nombre} ({m.tipo.upper()}: S/ {m.monto})" for m in a.movimientos.all()]
            resumen_diario.append(f"Asiento #{a.id} ({a.fecha}) - {a.descripcion}:\n  " + "\n  ".join(movs))

        contexto = "\n\n".join(resumen_diario) if resumen_diario else "No hay asientos registrados aún."

        client = groq.Groq(api_key=api_key)
        system_prompt = f"""
        Eres un profesor y auditor de contabilidad universitaria bajo el Plan Contable General Empresarial (PCGE) del Perú.
        Tu rol es sustentar y fundamentar técnicamente el LIBRO DIARIO de la empresa ante el docente.

        ASIENTOS REGISTRADOS:
        -----------------------------------
        {contexto}
        -----------------------------------

        Instrucciones:
        1. Explica técnicamente por qué una cuenta va al Debe o al Haber usando la teoría del cargo y abono (+Activo al Debe, -Activo al Haber, +Pasivo al Haber, etc.).
        2. Cita la cuenta contable y su código oficial según el PCGE.
        3. Sé formal, seguro y conciso (máximo 2 párrafos cortos).
        """

        chat_completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2,
        )

        respuesta = chat_completion.choices[0].message.content
        return JsonResponse({'response': respuesta, 'status': 'success'})

    except Exception as e:
        return JsonResponse({'error': f'Error en el asistente: {str(e)}'}, status=500)


# ─── INGESTA DE CASO POR IMAGEN / FOTO (GROQ VISION) ──────────────────────────

def cargar_imagen_diario(request):
    """
    Recibe una imagen de un ejercicio contable, la analiza mediante
    Groq + Qwen Vision y genera los asientos del Libro Diario.

    El sistema:
    1. Lee la imagen.
    2. Envía imagen + instrucciones al modelo.
    3. Obtiene JSON.
    4. Valida estructura y partida doble.
    5. Recién después guarda los asientos en la BD.
    """

    if request.method != 'POST':
        return render(request, 'cargar_imagen_diario.html')

    imagen_file = request.FILES.get('imagen_caso')

    # ==============================================================
    # 1. VALIDAR ARCHIVO
    # ==============================================================

    if not imagen_file:
        messages.error(
            request,
            'Debe adjuntar o capturar una foto del caso contable.'
        )
        return redirect('cargar_imagen_diario')

    # Tipos de imagen permitidos
    tipos_permitidos = {
        'image/jpeg',
        'image/jpg',
        'image/png',
        'image/webp',
    }

    mime_type = (
        getattr(imagen_file, 'content_type', None)
        or 'image/jpeg'
    ).lower()

    if mime_type not in tipos_permitidos:
        messages.error(
            request,
            'El archivo debe ser una imagen JPG, PNG o WEBP.'
        )
        return redirect('cargar_imagen_diario')

    # Groq permite imágenes de hasta 20 MB.
    max_size = 20 * 1024 * 1024

    if imagen_file.size > max_size:
        messages.error(
            request,
            'La imagen supera el límite permitido de 20 MB.'
        )
        return redirect('cargar_imagen_diario')

    # ==============================================================
    # 2. OBTENER API KEY DESDE SETTINGS / .ENV
    # ==============================================================

    api_key = settings.GROQ_API_KEY

    if not api_key:
        raise ValueError(
            'No se encontró GROQ_API_KEY en el archivo .env'
         )

    client = Groq(api_key=api_key)

    if not api_key:
        api_key = os.environ.get('GROQ_API_KEY', '')

    if not api_key:
        messages.error(
            request,
            'No se encontró GROQ_API_KEY. '
            'Configúrala en el archivo .env.'
        )
        return redirect('cargar_imagen_diario')

    try:

        # ==========================================================
        # 3. LEER Y CODIFICAR IMAGEN
        # ==========================================================

        img_bytes = imagen_file.read()

        if not img_bytes:
            raise ValueError(
                'La imagen está vacía o no pudo ser leída.'
            )

        img_b64 = base64.b64encode(img_bytes).decode('utf-8')

        # ==========================================================
        # 4. CREAR CLIENTE GROQ
        # ==========================================================

        client = groq.Groq(api_key=api_key)

        # ==========================================================
        # 5. PROMPT PARA VISIÓN
        # ==========================================================

        prompt_vision = """
Eres un contador experto en contabilidad financiera y en el
Plan Contable General Empresarial (PCGE) utilizado en Perú.

Analiza cuidadosamente la imagen del ejercicio contable.

Tu trabajo consiste en:

1. Leer TODAS las operaciones que aparecen en la imagen.
2. Identificar las fechas.
3. Identificar las cuentas involucradas.
4. Determinar qué cuenta corresponde al DEBE y cuál al HABER.
5. Determinar los importes.
6. Generar los asientos del Libro Diario.
7. Mantener la partida doble:
   la suma del DEBE debe ser exactamente igual a la suma del HABER
   en cada asiento.

MUY IMPORTANTE:

- NO INVENTES información que no pueda leerse.
- Si una parte de la imagen es ilegible o ambigua, intenta
  interpretarla únicamente si existe suficiente evidencia.
- Si una cifra, fecha o texto no puede determinarse con seguridad,
  utiliza el campo "observaciones" para indicarlo.
- No agregues operaciones que no aparezcan en la imagen.
- No elimines operaciones que sí aparezcan en la imagen.
- Respeta las fechas indicadas en el ejercicio.
- Usa cuentas contables coherentes con el PCGE.
- No confundas ingresos con cobros.
- No confundas compras con pagos.
- No confundas ventas con cobranzas.
- Si una operación afecta existencias, considera el efecto contable
  correspondiente cuando la información de la imagen lo permita.
- Cada asiento debe cuadrar: DEBE = HABER.

RESPONDE ÚNICAMENTE CON JSON VÁLIDO.

La estructura obligatoria es:

{
  "asientos": [
    {
      "fecha": "2009-04-01",
      "descripcion": "Asiento de apertura",
      "glosa": "Aporte inicial de los socios",
      "observaciones": "",
      "movimientos": [
        {
          "codigo": "10",
          "nombre": "Efectivo y Equivalentes de Efectivo",
          "tipo_cuenta": "activo",
          "tipo_movimiento": "debe",
          "monto": 10000.00
        },
        {
          "codigo": "50",
          "nombre": "Capital",
          "tipo_cuenta": "patrimonio",
          "tipo_movimiento": "haber",
          "monto": 10000.00
        }
      ]
    }
  ]
}

REGLAS:

"tipo_cuenta" solamente puede ser:

- activo
- pasivo
- patrimonio
- ingreso
- gasto

"tipo_movimiento" solamente puede ser:

- debe
- haber

"monto" debe ser un número positivo.

"fecha" debe utilizar el formato:

YYYY-MM-DD

No escribas comentarios.
No escribas Markdown.
No utilices ```json.
No escribas explicaciones antes ni después del JSON.

Si alguna información de la imagen no puede determinarse con
seguridad, NO inventes el dato. Indícalo en "observaciones".
"""

        # ==========================================================
        # 6. ENVIAR IMAGEN A GROQ
        # ==========================================================

        chat_resp = client.chat.completions.create(
            model='qwen/qwen3.8-27b',

            messages=[
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'text',
                            'text': prompt_vision
                        },
                        {
                            'type': 'image_url',
                            'image_url': {
                                'url': (
                                    f'data:{mime_type};base64,'
                                    f'{img_b64}'
                                )
                            }
                        }
                    ]
                }
            ],

            temperature=0.1,
            max_tokens=4096,

            # Qwen soporta JSON mode.
            response_format={
                'type': 'json_object'
            }
        )

        # ==========================================================
        # 7. OBTENER RESPUESTA
        # ==========================================================

        raw_txt = (
            chat_resp.choices[0]
            .message
            .content
            .strip()
        )

        if not raw_txt:
            raise ValueError(
                'El modelo no devolvió ninguna respuesta.'
            )

        # ==========================================================
        # 8. LIMPIAR POSIBLES BLOQUES MARKDOWN
        # ==========================================================

        raw_txt = re.sub(
            r'^```(?:json)?\s*',
            '',
            raw_txt,
            flags=re.IGNORECASE
        )

        raw_txt = re.sub(
            r'\s*```$',
            '',
            raw_txt
        ).strip()

        # ==========================================================
        # 9. CONVERTIR A JSON
        # ==========================================================

        try:
            datos = json.loads(raw_txt)

        except json.JSONDecodeError:

            # Fallback por si el modelo devolviera texto adicional.
            match = re.search(
                r'\{.*\}',
                raw_txt,
                re.DOTALL
            )

            if not match:
                raise ValueError(
                    'La IA no devolvió un JSON válido.'
                )

            try:
                datos = json.loads(match.group(0))

            except json.JSONDecodeError:
                raise ValueError(
                    'No fue posible interpretar la respuesta JSON '
                    'generada por la IA.'
                )

        # ==========================================================
        # 10. EXTRAER ASIENTOS
        # ==========================================================

        if not isinstance(datos, dict):
            raise ValueError(
                'La respuesta de la IA no tiene el formato esperado.'
            )

        asientos_json = datos.get('asientos', [])

        if not isinstance(asientos_json, list):
            raise ValueError(
                'El campo "asientos" no contiene una lista válida.'
            )

        if not asientos_json:
            raise ValueError(
                'No se pudieron identificar asientos contables '
                'en la imagen.'
            )

        # ==========================================================
        # 11. VALIDACIONES ANTES DE TOCAR LA BASE DE DATOS
        # ==========================================================

        tipos_cuenta_validos = {
            'activo',
            'pasivo',
            'patrimonio',
            'ingreso',
            'gasto',
        }

        tipos_movimiento_validos = {
            'debe',
            'haber',
        }

        asientos_validados = []

        for numero_asiento, item in enumerate(
            asientos_json,
            start=1
        ):

            if not isinstance(item, dict):
                raise ValueError(
                    f'El asiento #{numero_asiento} '
                    f'no tiene un formato válido.'
                )

            fecha_val = item.get('fecha')

            if not fecha_val:
                raise ValueError(
                    f'El asiento #{numero_asiento} '
                    f'no tiene fecha.'
                )

            fecha_val = str(fecha_val).strip()

            # ------------------------------------------------------
            # Validar fecha
            # ------------------------------------------------------

            try:
                from datetime import datetime

                fecha_obj = datetime.strptime(
                    fecha_val,
                    '%Y-%m-%d'
                ).date()

            except ValueError:
                raise ValueError(
                    f'La fecha "{fecha_val}" del asiento '
                    f'#{numero_asiento} no tiene formato YYYY-MM-DD.'
                )

            movimientos = item.get(
                'movimientos',
                []
            )

            if not isinstance(movimientos, list):
                raise ValueError(
                    f'Los movimientos del asiento '
                    f'#{numero_asiento} no son válidos.'
                )

            if not movimientos:
                raise ValueError(
                    f'El asiento #{numero_asiento} '
                    f'no contiene movimientos.'
                )

            debe = Decimal('0.00')
            haber = Decimal('0.00')

            movimientos_validados = []

            for numero_mov, mov in enumerate(
                movimientos,
                start=1
            ):

                if not isinstance(mov, dict):
                    raise ValueError(
                        f'El movimiento #{numero_mov} '
                        f'del asiento #{numero_asiento} '
                        f'no es válido.'
                    )

                codigo = str(
                    mov.get('codigo', '')
                ).strip()

                nombre = str(
                    mov.get('nombre', '')
                ).strip()

                tipo_cuenta = str(
                    mov.get('tipo_cuenta', '')
                ).strip().lower()

                tipo_movimiento = str(
                    mov.get('tipo_movimiento', '')
                ).strip().lower()

                # --------------------------------------------------
                # Validar código
                # --------------------------------------------------

                if not codigo:
                    raise ValueError(
                        f'El movimiento #{numero_mov} '
                        f'del asiento #{numero_asiento} '
                        f'no tiene código de cuenta.'
                    )

                # --------------------------------------------------
                # Validar nombre
                # --------------------------------------------------

                if not nombre:
                    raise ValueError(
                        f'La cuenta {codigo} no tiene nombre.'
                    )

                # --------------------------------------------------
                # Validar tipo de cuenta
                # --------------------------------------------------

                if tipo_cuenta not in tipos_cuenta_validos:
                    raise ValueError(
                        f'La cuenta {codigo} tiene un tipo inválido: '
                        f'"{tipo_cuenta}".'
                    )

                # --------------------------------------------------
                # Validar DEBE / HABER
                # --------------------------------------------------

                if tipo_movimiento not in tipos_movimiento_validos:
                    raise ValueError(
                        f'La cuenta {codigo} tiene un movimiento '
                        f'inválido: "{tipo_movimiento}".'
                    )

                # --------------------------------------------------
                # Validar monto
                # --------------------------------------------------

                monto_raw = mov.get('monto')

                if monto_raw is None:
                    raise ValueError(
                        f'La cuenta {codigo} no tiene monto.'
                    )

                try:
                    monto = Decimal(str(monto_raw))

                except (
                    InvalidOperation,
                    ValueError,
                    TypeError
                ):
                    raise ValueError(
                        f'El monto de la cuenta {codigo} '
                        f'no es válido.'
                    )

                if monto <= Decimal('0'):
                    raise ValueError(
                        f'El monto de la cuenta {codigo} '
                        f'debe ser mayor que cero.'
                    )

                monto = monto.quantize(
                    Decimal('0.01')
                )

                # --------------------------------------------------
                # Acumular DEBE / HABER
                # --------------------------------------------------

                if tipo_movimiento == 'debe':
                    debe += monto
                else:
                    haber += monto

                movimientos_validados.append({
                    'codigo': codigo,
                    'nombre': nombre,
                    'tipo_cuenta': tipo_cuenta,
                    'tipo_movimiento': tipo_movimiento,
                    'monto': monto,
                })

            # ======================================================
            # 12. VALIDAR PARTIDA DOBLE
            # ======================================================

            diferencia = abs(debe - haber)

            if diferencia > Decimal('0.01'):
                raise ValueError(
                    f'El asiento #{numero_asiento} no cuadra. '
                    f'Debe: S/ {debe:.2f} | '
                    f'Haber: S/ {haber:.2f} | '
                    f'Diferencia: S/ {diferencia:.2f}'
                )

            # ======================================================
            # GUARDAR ASIENTO YA VALIDADO EN MEMORIA
            # ======================================================

            asientos_validados.append({
                'fecha': fecha_obj,
                'descripcion': str(
                    item.get(
                        'descripcion',
                        'Asiento Contable'
                    )
                ).strip(),

                'glosa': str(
                    item.get(
                        'glosa',
                        ''
                    )
                ).strip(),

                'observaciones': str(
                    item.get(
                        'observaciones',
                        ''
                    )
                ).strip(),

                'movimientos': movimientos_validados,

                'debe': debe,
                'haber': haber,
            })

        # ==========================================================
        # 13. RECIÉN AHORA MODIFICAR LA BASE DE DATOS
        # ==========================================================

        with transaction.atomic():

            # Si el usuario marcó "limpiar", recién ahora
            # eliminamos los datos anteriores.
            if request.POST.get('limpiar') == 'on':

                Movimiento.objects.all().delete()

                AsientoContable.objects.all().delete()

            total_creados = 0

            for item in asientos_validados:

                descripcion = item['descripcion']

                if item['glosa']:
                    descripcion += (
                        f" | {item['glosa']}"
                    )

                # --------------------------------------------------
                # Crear asiento
                # --------------------------------------------------

                asiento = AsientoContable.objects.create(
                    fecha=item['fecha'],
                    descripcion=descripcion
                )

                # --------------------------------------------------
                # Crear movimientos
                # --------------------------------------------------

                for mov in item['movimientos']:

                    codigo = mov['codigo']
                    nombre = mov['nombre']
                    tipo_cta = mov['tipo_cuenta']

                    # Buscar o crear cuenta
                    cuenta, creada = (
                        CuentaContable.objects.get_or_create(
                            codigo=codigo,
                            defaults={
                                'nombre': nombre,
                                'tipo': tipo_cta,
                            }
                        )
                    )

                    # ------------------------------------------------
                    # Crear movimiento
                    # ------------------------------------------------

                    Movimiento.objects.create(
                        asiento=asiento,
                        cuenta=cuenta,
                        tipo=mov['tipo_movimiento'],
                        monto=mov['monto'],
                    )

                total_creados += 1

        # ==========================================================
        # 14. MOSTRAR RESULTADO
        # ==========================================================

        observaciones = []

        for item in asientos_validados:

            if item['observaciones']:
                observaciones.append(
                    item['observaciones']
                )

        mensaje = (
            f'¡Éxito! Se reconocieron y guardaron '
            f'{total_creados} asientos contables.'
        )

        if observaciones:
            mensaje += (
                ' La IA indicó algunas observaciones: '
                + ' | '.join(observaciones)
            )

        messages.success(
            request,
            mensaje
        )

        return redirect('libro_diario')

    # ==============================================================
    # 15. MANEJO DE ERRORES
    # ==============================================================

    except Exception as e:

        messages.error(
            request,
            f'Error al procesar la imagen: {str(e)}'
        )

        return redirect(
            'cargar_imagen_diario'
        )
