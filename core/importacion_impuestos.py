"""Solicita la tasa únicamente cuando hay un impuesto sin porcentaje leído."""
import re


def necesita_tasa(datos):
    operaciones = datos.get('operaciones', [])
    for op in operaciones:
        if not isinstance(op, dict):
            continue
        if op.get('impuesto') in ('incluido', 'neto') and op.get('tasa_impuesto') is None:
            return True
        if op.get('tipo') == 'no_soportada':
            texto = str(op.get('texto') or '')
            if re.search(r'\b(?:IGV|IVA)\b', texto, re.I) and op.get('tasa_impuesto') is None:
                return True
    return False
