"""Asignación explícita, reversible y sin cambiar códigos ni importes."""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.core.exceptions import ValidationError
from core.workspaces import acceso_administrativo
from core.models import Workspace, CuentaContable, AsientoContable, FinancialRatioPeriod, RespaldoCaso


class Command(BaseCommand):
    help = 'Inspecciona el histórico sin espacio. --workspace UUID --confirmar lo asigna explícitamente sin cuenta.'

    def add_arguments(self, parser):
        destino = parser.add_mutually_exclusive_group(required=True)
        destino.add_argument('--workspace')
        destino.add_argument('--usuario', help='Compatibilidad administrativa; no vincula el acceso público al usuario.')
        parser.add_argument('--confirmar', action='store_true')

    @acceso_administrativo()
    def handle(self, *args, **options):
        user = None
        workspace = None
        if options.get('workspace'):
            try: workspace = Workspace.objects.get(pk=options['workspace'])
            except (ValidationError, Workspace.DoesNotExist): raise CommandError('El espacio de destino no existe.') from None
        else:
            try: user = get_user_model().objects.get(username=options['usuario'])
            except get_user_model().DoesNotExist: raise CommandError('El usuario no existe.') from None
        modelos = (CuentaContable, AsientoContable, FinancialRatioPeriod, RespaldoCaso)
        for modelo in modelos:
            self.stdout.write(f'{modelo.__name__}: {modelo.objects.filter(workspace__isnull=True).count()} registros sin propietario')
        if not options['confirmar']:
            self.stdout.write('Simulación: no se modificó ningún registro. Haga respaldo de la BD antes de --confirmar.')
            return
        with transaction.atomic():
            workspace = workspace or (Workspace.objects.filter(owner=user).first() if user else None)
            if workspace and any(modelo.objects.filter(workspace=workspace).exists() for modelo in modelos):
                raise CommandError('El espacio de destino ya tiene datos. Use un espacio vacío para no mezclar registros.')
            if workspace is None: workspace = Workspace.objects.create(owner=user)
            for modelo in modelos:
                modelo.objects.filter(workspace__isnull=True).update(workspace=workspace)
        self.stdout.write(f'Asignados sin renumerar ni cambiar importes. Workspace {workspace.pk}')
