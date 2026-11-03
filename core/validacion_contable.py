"""Controles deterministas; nunca se altera un asiento histórico para cuadrarlo."""
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP

FUENTE_PCGE = 'https://www.mef.gob.pe/contenidos/conta_publ/documentac/PCGE_2019.pdf'


def texto(valor):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(valor).lower()) if not unicodedata.combining(c))


def grupo_esperado(nombre, tipo):
    n = texto(nombre)
    if tipo == 'activo':
        if re.search(r'\bcaja\b|\bbancos?\b|efectivo|cuenta.*corriente', n): return '10'
        if re.search(r'mercader|inventario de mercader', n): return '20'
        from .contexto_importacion import familias_inventario
        inventarios=familias_inventario(n)
        if len(inventarios)==1:return next(iter(inventarios))
        if re.search(r'depreciacion acumulada|amortizacion acumulada', n): return '39'
        if re.search(r'equipo|maquinaria|mobiliario|vehiculo', n) and not re.search(r'para.*venta|por cobrar|anticipo', n): return '33'
    if tipo == 'pasivo':
        if re.search(r'proveedor|pasivos? por compra', n) and re.search(r'equipos?|activo (?:fijo|inmovilizado)|maquinaria', n):
            return '47' if 'relacionad' in n else '46'
    if tipo == 'patrimonio' and re.fullmatch(r'capital(?: social)?', n.strip()): return '50'
    from .clasificacion import venta_ordinaria
    if tipo == 'ingreso' and venta_ordinaria(n): return '70'
    if tipo == 'gasto' and re.search(r'costo.*ventas', n): return '69'
    if tipo == 'gasto' and re.search(r'depreciacion|amortizacion', n): return '68'
    if tipo == 'gasto' and re.search(r'\bplanilla\b|sueldos?|salarios?|remuneracion|gastos? de personal', n): return '62'
    return None


def validar_cuenta(codigo, nombre, tipo):
    if not re.fullmatch(r'\d{2,20}', str(codigo)):
        raise ValueError('El código de cuenta debe contener entre 2 y 20 dígitos.')
    grupo = int(str(codigo)[:2])
    compatible = (tipo == 'activo' and 10 <= grupo <= 39 or
                  tipo == 'pasivo' and 40 <= grupo <= 49 or
                  tipo == 'patrimonio' and 50 <= grupo <= 59 or
                  tipo == 'gasto' and (60 <= grupo <= 69 or grupo == 88 or 90 <= grupo <= 99) or
                  tipo == 'ingreso' and 70 <= grupo <= 79)
    esperado = grupo_esperado(nombre, tipo)
    from .contexto_importacion import inventario_generico,INVENTARIOS
    if tipo == 'activo' and inventario_generico(nombre) and str(codigo)[:2] not in {*INVENTARIOS,'28'}:
        raise ValueError(f'Cuenta {codigo} — {nombre}: no identifica una familia de inventarios. Aclare si son mercaderías, materias primas u otro tipo de existencias.')
    if tipo == 'pasivo' and re.search(r'\bproveedores?\b', texto(nombre)) and grupo not in (42,43,46,47):
        compatible = False
    if not compatible or esperado and not str(codigo).startswith(esperado):
        raise ValueError(f'Cuenta {codigo} — {nombre}: código incompatible con {tipo} según las familias PCGE' + (f'; corresponde revisar el grupo {esperado}.' if esperado else '.'))


def preparar_pcge(asientos, fuente=''):
    """Solo borradores nuevos: corrige familias reconocibles, no libros históricos."""
    from copy import deepcopy
    from .clasificacion import rubro_resultados
    from types import SimpleNamespace
    salida = deepcopy(asientos)
    from .contexto_importacion import inventario_generico,familia_del_inventario,INVENTARIOS
    inventarios_validos={}
    for a in salida:
        for m in a.get('movimientos',[]):
            if m.get('tipo_cuenta')=='activo' and (inventario_generico(m.get('nombre','')) or
                                                  grupo_esperado(m.get('nombre',''),'activo') in INVENTARIOS):
                g=str(m.get('codigo',''))[:2]
                if g in INVENTARIOS:inventarios_validos.setdefault(g,{})[str(m['codigo'])]=m
    inventarios_corregidos={}
    # Inferir el proveedor solo desde compras inequívocas del mismo borrador.
    # Una cuenta que mezcla equipos y mercaderías necesita revisión manual.
    origenes = {}
    for a in salida:
        movs = a.get('movimientos', [])
        compra_activo = any(m.get('tipo_cuenta') == 'activo' and
                            (grupo_esperado(m.get('nombre',''),'activo') == '33' or
                             str(m.get('codigo','')).startswith('33')) and
                            m.get('tipo_movimiento') == 'debe' for m in movs)
        compra_comercial = any((m.get('tipo_cuenta') == 'activo' and
                                (grupo_esperado(m.get('nombre',''),'activo') in INVENTARIOS or
                                 inventario_generico(m.get('nombre','')) and familia_del_inventario(a,fuente) in INVENTARIOS) or
                                m.get('tipo_cuenta') == 'gasto' and str(m.get('codigo','')).startswith(('60','62','63'))) and
                               m.get('tipo_movimiento') == 'debe' for m in movs)
        for m in movs:
            if m.get('tipo_cuenta') == 'pasivo' and re.search(r'\bproveedores?\b', texto(m.get('nombre',''))):
                key = (str(m.get('codigo','')), texto(m.get('nombre','')), 'pasivo')
                if compra_activo: origenes.setdefault(key,set()).add('46')
                if compra_comercial: origenes.setdefault(key,set()).add('42')
    elegidos = {}
    ocupados = {str(m.get('codigo')): (texto(m.get('nombre', '')), m.get('tipo_cuenta'))
                for a in salida for m in a.get('movimientos', [])}
    for a in salida:
        for m in a.get('movimientos', []):
            codigo = str(m.get('codigo', ''))
            nombre, tipo = m.get('nombre', ''), m.get('tipo_cuenta', '')
            # Solo el borrador nuevo: no perpetuar una etiqueta de IA que
            # convierte ventas identificables en otros ingresos.
            sub = m.get('subcategoria', '')
            if tipo == 'ingreso' and texto(sub).strip().replace(' ', '_') == 'otro_ingreso':
                cuenta = SimpleNamespace(codigo=codigo, nombre=nombre, tipo=tipo, subcategoria=sub)
                if rubro_resultados(cuenta) == 'ventas':
                    m['subcategoria'] = ''
            grupo = grupo_esperado(nombre, tipo)
            if tipo=='activo' and inventario_generico(nombre):
                grupo=familia_del_inventario(a,fuente)
                if grupo and not codigo.startswith(grupo):
                    validos=inventarios_validos.get(grupo,{})
                    if len(validos)>1:continue
                    if len(validos)==1:
                        cuenta=next(iter(validos.values()))
                        m.update({k:cuenta.get(k,'') for k in ('codigo','nombre','subcategoria')})
                        m['subcategoria']='activo_corriente'
                        continue
                    corregidos=inventarios_corregidos.get(grupo,{})
                    if len(corregidos)>1:continue
                    if len(corregidos)==1:
                        cuenta=next(iter(corregidos.values()))
                        m.update({k:cuenta.get(k,'') for k in ('codigo','nombre','subcategoria')})
                        m['subcategoria']='activo_corriente'
                        continue
            if tipo=='activo' and grupo in INVENTARIOS:m['subcategoria']='activo_corriente'
            if tipo=='activo' and grupo in ('33','39'):m['subcategoria']='activo_no_corriente'
            if tipo=='gasto' and grupo in ('62','68'):m['subcategoria']='gasto_operativo'
            if tipo=='gasto' and grupo=='69':m['subcategoria']='costo_ventas'
            if not grupo and tipo == 'pasivo' and not codigo.startswith(('42','43','46','47')):
                origen = origenes.get((codigo,texto(nombre),tipo),set())
                if len(origen) == 1: grupo = next(iter(origen))
            if grupo and not codigo.startswith(grupo):
                clave = (codigo, texto(nombre), tipo)
                if clave not in elegidos:
                    base = {'10': '101', '20': '201', '21':'211','22':'221','23':'231','24':'241','25':'251','26':'261','33': '336', '39': '39',
                            '42': '421', '46': '4654', '47': '477', '50': '501', '62':'62','68':'68','70': '70', '69': '69'}[grupo]
                    # Sin documento no se puede decidir 4211/4212. No mezclar
                    # proveedores ni inventar una subdivision para evitar el choque.
                    if grupo in ('42','47') and base in ocupados:
                        continue
                    candidato = base
                    sufijo = 1
                    while candidato in ocupados:
                        candidato = base + str(sufijo)
                        sufijo += 1
                    elegidos[clave] = candidato
                    ocupados[candidato] = (texto(nombre),tipo)
                m['codigo'] = elegidos[clave]
                if tipo=='activo' and grupo in INVENTARIOS:
                    inventarios_corregidos.setdefault(grupo,{})[m['codigo']]=m
    return salida


def importe_escrito(valor):
    n = re.sub(r'[^\d.,-]', '', valor)
    if ',' in n and '.' in n:
        decimal = ',' if n.rfind(',') > n.rfind('.') else '.'
        n = n.replace('.' if decimal == ',' else ',', '').replace(decimal, '.')
    elif ',' in n or '.' in n:
        sep = ',' if ',' in n else '.'
        partes = n.split(sep)
        n = ''.join(partes) if len(partes[-1]) == 3 else ''.join(partes[:-1]) + '.' + partes[-1]
    return Decimal(n)


def auditar_asientos(asientos, fuente=''):
    alertas = []
    saldo = Decimal('0')
    vistos = set()
    for i, a in enumerate(asientos, 1):
        movs = a['movimientos']
        glosa = texto(a.get('descripcion', ''))
        firma = (str(a.get('fecha', '')), glosa, tuple(sorted((str(m['codigo']), m['tipo_movimiento'], str(m['monto'])) for m in movs)))
        if firma in vistos:
            alertas.append(f'Asiento {i}: posible operación duplicada (misma fecha, glosa y movimientos). Aclare el documento antes de guardar.')
        vistos.add(firma)
        inventario = [m for m in movs if m['tipo_cuenta'] == 'activo' and
                      (str(m['codigo']).startswith(('20','21','22','23','24','25','26','28')) or re.search(r'mercader|inventario|existencia', texto(m['nombre'])))]
        cambio = sum((Decimal(str(m['monto'])) * (1 if m['tipo_movimiento'] == 'debe' else -1) for m in inventario), Decimal('0'))
        previo = saldo
        saldo += cambio
        if inventario and any(m['tipo_cuenta'] == 'patrimonio' for m in movs) and re.search(r'ajuste|costo.*venta|inventario.*final|inventario.*fisico', glosa):
            alertas.append(f'Asiento {i}: el ajuste de inventario afecta al capital/patrimonio. Revise costo de ventas o pérdida; no use capital para cuadrar.')
        if any(m['tipo_cuenta'] == 'patrimonio' and (str(m['codigo']).startswith('50') or re.fullmatch(r'capital(?: social)?', texto(m['nombre']).strip())) and m['tipo_movimiento'] == 'debe' for m in movs) and not re.search(r'retiro|reduccion.*capital|devolucion.*aporte|disminucion.*capital', glosa):
            alertas.append(f'Asiento {i}: disminución de capital sin retiro o reducción documentada en la glosa.')
        valores = re.findall(r'inventario[^\n.]{0,60}(?:fisico|final)[^\d\n]{0,35}([\d][\d.,]*)', glosa)
        if valores and inventario:
            fisico = importe_escrito(valores[-1])
            if fisico != saldo:
                alertas.append(f'Asiento {i}: inventario físico S/ {fisico:,.2f}, saldo contable S/ {saldo:,.2f}; diferencia S/ {saldo-fisico:,.2f}. Saldo previo S/ {previo:,.2f}; reducción neta requerida S/ {previo-fisico:,.2f}, sujeta a revisar la contrapartida.')
    n = texto(fuente)
    depreciaciones=any(m['tipo_cuenta']=='gasto' and
                      re.search(r'depreciacion|amortizacion',texto(m['nombre']))
                      for a in asientos for m in a['movimientos'])
    if (n.strip() and depreciaciones and
            not re.search(r'depreciacion|amortizacion|vida util|valor residual',n)):
        alertas.append('La propuesta añade depreciación o amortización sin datos que sustenten ese ajuste en el enunciado. Retire el ajuste o complete su base antes de guardar; no se inventan tasas ni importes.')
    from .clasificacion import fecha_cierre_del_caso
    from .contexto_importacion import es_ajuste_de_cierre,familias_inventario
    cierre=fecha_cierre_del_caso({'texto_leido':fuente},solo_periodo_unico=True)
    if cierre:
        for i,a in enumerate(asientos,1):
            if es_ajuste_de_cierre(a) and a.get('fecha') and str(a['fecha'])!=cierre.isoformat():
                alertas.append(f'Asiento {i}: el ajuste corresponde al cierre {cierre.isoformat()}, pero tiene fecha {a["fecha"]}. Corrija la fecha antes de guardar.')
    for i,a in enumerate(asientos,1):
        glosa=texto(a.get('descripcion',''))
        if (re.search(r'servicios?',glosa) and not re.search(r'personal|planilla|sueld|remuneracion',glosa) and
                any(m['tipo_cuenta']=='gasto' and grupo_esperado(m['nombre'],'gasto')=='62' for m in a['movimientos'])):
            alertas.append(f'Asiento {i}: una operación descrita como servicios usa gastos de personal; revise el gasto de servicios del grupo 63 y no reutilice la cuenta de planilla.')
        es_depreciacion=any(m['tipo_cuenta']=='gasto' and 'depreciacion' in texto(m['nombre']) for m in a['movimientos'])
        if es_depreciacion and any(m['tipo_cuenta']=='activo' and str(m['codigo']).startswith('33') and m['tipo_movimiento']=='haber' for m in a['movimientos']):
            alertas.append(f'Asiento {i}: la depreciación debe separar el costo del activo y su depreciación acumulada del grupo 39; revise el abono directo al grupo 33.')
    tasas=re.findall(r'depreciacion[^.\n%]{0,80}?anual[^\d%]{0,80}(\d+(?:[.,]\d+)?)\s*%',n)
    if cierre and len(tasas)==1 and not re.search(r'residual|salvamento|rescate|acelerad|unidades de produccion',n):
        from datetime import date
        activos=[(a,m) for a in asientos for m in a['movimientos'] if m['tipo_cuenta']=='activo' and str(m['codigo']).startswith('33') and m['tipo_movimiento']=='debe']
        if len(activos)==1:
            a,m=activos[0]
            try:inicio=date.fromisoformat(str(a.get('fecha','')))
            except ValueError:inicio=None
            if inicio and inicio.day==1 and (inicio.year,inicio.month)==(cierre.year,cierre.month):
                mensual=(Decimal(str(m['monto']))*importe_escrito(tasas[0])/100/12).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                anual=(Decimal(str(m['monto']))*importe_escrito(tasas[0])/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                registrada=sum((Decimal(str(m['monto'])) for a in asientos for m in a['movimientos'] if m['tipo_cuenta']=='gasto' and 'depreciacion' in texto(m['nombre']) and m['tipo_movimiento']=='debe'),Decimal('0'))
                if registrada and registrada==anual and anual!=mensual:
                    alertas.append(f'La tasa de depreciación es anual y el período identificado es un mes; con prorrateo mensual sobre el activo registrado la cuota sería S/ {mensual:,.2f}, pero se propuso S/ {registrada:,.2f}; confirme el criterio temporal y corrija el ajuste antes de guardar.')
    tiene_inventario = any(m['tipo_cuenta'] == 'activo' and
                           (str(m['codigo']).startswith(('20','21','22','23','24','25','26','28')) or
                            re.search(r'inventario|mercader|existencia', texto(m['nombre'])))
                           for a in asientos for m in a['movimientos'])
    if (tiene_inventario and re.search(r'consultor|servicios? de soporte',n) and not familias_inventario(n) and
            not re.search(r'mercader|inventari|existenci|productos?|stock|insumos?|materiales|repuestos|bienes para.*venta',n)):
        alertas.append('La propuesta incluye inventarios, pero el enunciado de servicios no describe existencias ni compras de mercaderías. Revise y retire la operación sin sustento; no se puede inventar inventario ni costo de ventas.')
    patrones = [r'inventario\s+(?:fisico\s+)?final[^\d\n]{0,65}([\d][\d.,]*)',
                r'inventario[^\n]{0,35}saldo\s+final[^\d\n]{0,30}([\d][\d.,]*)']
    finales = [x for patron in patrones for x in re.findall(patron, n)]
    if finales:
        fisico = importe_escrito(finales[-1])
        if saldo != fisico:
            alertas.append(f'El inventario físico del enunciado es S/ {fisico:,.2f}; los asientos dejan S/ {saldo:,.2f}. Conciliar antes de guardar.')
    return list(dict.fromkeys(alertas))


def importes_auditables(asientos):
    """Un código inválido no debe ocultar los otros controles del borrador."""
    from decimal import InvalidOperation
    try:
        return all(Decimal(str(m['monto'])).is_finite() and Decimal(str(m['monto']))>=0
                   for a in asientos for m in a['movimientos'])
    except (InvalidOperation,ValueError,TypeError,KeyError):return False
