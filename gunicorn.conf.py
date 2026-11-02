"""Punto de partida conservador; dimensionar con el plan y mediciones reales."""
import os

bind = '0.0.0.0:' + os.getenv('PORT', '8000')
workers = int(os.getenv('WEB_CONCURRENCY', '1'))
threads = int(os.getenv('GUNICORN_THREADS', '1'))
worker_class = 'gthread' if threads > 1 else 'sync'
timeout = int(os.getenv('GUNICORN_TIMEOUT', '180'))
graceful_timeout = 30
max_requests = 200
max_requests_jitter = 30
accesslog = '-'
errorlog = '-'
capture_output = True
if workers < 1 or threads < 1 or timeout < 1:
    raise ValueError('Workers, threads y timeout deben ser positivos.')


def on_starting(server):
    # Gunicorn carga este archivo también con el Start Command ya configurado
    # en Render: gunicorn contabilidad.wsgi:application.
    from contabilidad.arranque import preparar_base
    preparar_base()
