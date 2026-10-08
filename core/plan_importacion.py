"""Reutiliza las cuentas del plan sin renumerar movimientos existentes."""
from copy import deepcopy
import re
import unicodedata
from .models import CuentaContable


def identidad(nombre):
    nombre = ''.join(c for c in unicodedata.normalize('NFKD', nombre.casefold())
                     if not unicodedata.combining(c))
    nombre = re.sub(r'[^a-z0-9]+', ' ', nombre).strip()
    return {'capital social': 'capital', 'caja efectivo': 'caja',
            'efectivo en caja': 'caja', 'cuentas por cobrar comerciales': 'clientes',
            'equipos de computo': 'equipo de computo',
            'equipos de oficina': 'equipo de oficina'}.get(nombre, nombre)


def reutilizar_plan(asientos):
    resultado = deepcopy(asientos)
    cuentas = list(CuentaContable.objects.all())
    por_codigo = {c.codigo: c for c in cuentas}
    por_nombre = {}
    for c in cuentas:
        por_nombre.setdefault((identidad(c.nombre), c.tipo), []).append(c)
    nuevas = {}
    for asiento in resultado:
        for m in asiento['movimientos']:
            clave = (identidad(m['nombre']), m['tipo_cuenta'])
            coincidencias = por_nombre.get(clave, [])
            if coincidencias:
                # Las cuentas equivalentes heredadas no deben impedir importar.
                # Conservar una elección estable entre casos, sin fusionar ni
                # modificar movimientos anteriores.
                coincidencias = sorted(coincidencias, key=lambda c: c.pk)
                cuenta = coincidencias[0]
                m['codigo'], m['nombre'] = cuenta.codigo, cuenta.nombre
            elif clave in nuevas:
                m['codigo'], m['nombre'] = nuevas[clave]
            else:
                codigo = m['codigo']
                existente = por_codigo.get(codigo)
                if existente and identidad(existente.nombre) != clave[0]:
                    raise ValueError(f'El código {codigo} ya pertenece a {existente.nombre}, no a {m["nombre"]}. Revise el plan de cuentas.')
                if any(codigo == c for c, _ in nuevas.values()):
                    raise ValueError(f'El código {codigo} se propuso para cuentas distintas. Revise la propuesta.')
                nuevas[clave] = (codigo, m['nombre'])
    return resultado
