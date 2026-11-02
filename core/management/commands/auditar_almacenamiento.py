"""Inventario de solo lectura: nunca limpia sesiones, casos ni respaldos."""
import json
from datetime import timedelta
from uuid import UUID
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Exists, OuterRef, Sum, TextField
from django.db.models.functions import Cast, Length
from django.utils import timezone
from core.models import Workspace, CuentaContable, AsientoContable, Movimiento, RespaldoCaso, FinancialRatioPeriod
from core.workspaces import acceso_administrativo


class Command(BaseCommand):
    help = 'Informe JSON de almacenamiento y espacios vacíos para revisión humana. No borra ni modifica datos.'

    def add_arguments(self, parser):
        parser.add_argument('--dias-minimo', type=int, default=180)
        parser.add_argument('--limite', type=int, default=100)
        parser.add_argument('--max-sesiones', type=int, default=10000)

    @acceso_administrativo()
    def handle(self, *args, **options):
        if options['dias_minimo'] < 180 or not 1 <= options['limite'] <= 1000 or not 1 <= options['max_sesiones'] <= 100000:
            raise CommandError('Use al menos 180 días, límite 1–1000 y max-sesiones 1–100000.')
        ahora = timezone.now()
        vivas = Session.objects.filter(expire_date__gt=ahora)
        numero_vivas = vivas.count()
        motor_db = settings.SESSION_ENGINE in ('django.contrib.sessions.backends.db', 'django.contrib.sessions.backends.cached_db')
        escaneo_completo = motor_db and numero_vivas <= options['max_sesiones']
        enlazados = set()
        if motor_db:
            for sesion in vivas.order_by('pk')[:options['max_sesiones']].iterator(chunk_size=200):
                valor = sesion.get_decoded().get('workspace_id')
                try: enlazados.add(UUID(str(valor)))
                except (ValueError, TypeError, AttributeError): pass
        modelos = (CuentaContable, AsientoContable, RespaldoCaso, FinancialRatioPeriod)
        candidatos = Workspace.objects.none()
        if escaneo_completo:
            candidatos = Workspace.objects.filter(owner__isnull=True,
                created_at__lt=ahora-timedelta(days=options['dias_minimo'])).exclude(pk__in=enlazados)
            for indice, modelo in enumerate(modelos):
                campo = f'tiene_datos_{indice}'
                candidatos = candidatos.annotate(**{campo:Exists(modelo.objects.filter(workspace_id=OuterRef('pk')))}).filter(**{campo:False})
        caracteres = RespaldoCaso.objects.aggregate(total=Sum(Length(Cast('datos', TextField()))+Length(Cast('catalogo', TextField()))))['total'] or 0
        informe = {
            'generado':ahora.isoformat(), 'solo_lectura':True,
            'workspaces':Workspace.objects.count(),
            'workspaces_anonimos':Workspace.objects.filter(owner__isnull=True).count(),
            'registros':{modelo.__name__:modelo.objects.count() for modelo in (*modelos, Movimiento)},
            'caracteres_json_respaldos':caracteres,
            'sesiones_vigentes':numero_vivas,
            'sesiones_expiradas':Session.objects.filter(expire_date__lte=ahora).count(),
            'escaneo_sesiones_completo':escaneo_completo,
            'dias_minimo':options['dias_minimo'],
            'candidatos_vacios_total':candidatos.count(),
            'candidatos_vacios_revision':[
                {'workspace':str(w.pk),'creado':w.created_at.isoformat()}
                for w in candidatos.order_by('created_at','pk')[:options['limite']]],
            'nota':'No demuestra abandono. Revisar manualmente; no se borraron espacios, sesiones ni respaldos. Caracteres JSON no equivalen a bytes físicos de la base.',
        }
        self.stdout.write(json.dumps(informe, ensure_ascii=False))
