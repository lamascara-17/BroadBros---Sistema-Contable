#!/usr/bin/env bash
set -euo pipefail
# No crea bases ni aplica migraciones durante un arranque.
python manage.py migrate --check
exec python -m gunicorn contabilidad.wsgi:application --config gunicorn.conf.py
