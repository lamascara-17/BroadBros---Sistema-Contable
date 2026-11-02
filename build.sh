#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements-render.txt
python manage.py collectstatic --no-input
# La base temporal se prepara en el runtime, nunca en el entorno del build.
python manage.py check
