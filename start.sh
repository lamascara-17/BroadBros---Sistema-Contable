#!/usr/bin/env bash
set -euo pipefail
# El mismo hook de Gunicorn comprueba/prepara la base antes de crear workers.
exec python -m gunicorn contabilidad.wsgi:application --config gunicorn.conf.py
