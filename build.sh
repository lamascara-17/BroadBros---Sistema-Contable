#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements-render.txt
python manage.py collectstatic --no-input
# Las migraciones se ejecutan por separado, solo tras respaldo y aprobación.
python manage.py check
