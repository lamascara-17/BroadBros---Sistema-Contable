"""Asignación explícita, reversible y sin cambiar códigos ni importes."""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from core.models import Workspace, CuentaContable, AsientoContable, FinancialRatioPeriod, RespaldoCaso


class Command(BaseCommand):
    help = 'Inspecciona registros históricos sin propietario. --confirmar los asigna a un usuario existente.'

    def add_arguments(self, parser):
        parser.add_argument('--usuario', required=True)
        parser.add_argument('--confirmar', action='store_true')

    def handle(self, *args, **options):
        try: user = get_user_model().objects.get(username=options['usuario'])
        except get_user_model().DoesNotExist: raise CommandError('El usuario no existe.')
        modelos = (CuentaContable, AsientoContable, FinancialRatioPeriod, RespaldoCaso)
        for modelo in modelos:
            self.stdout.write(f'{modelo.__name__}: {modelo.objects.filter(workspace__isnull=True).count()} registros sin propietario')
        if not options['confirmar']:
            self.stdout.write('Simulación: no se modificó ningún registro. Haga respaldo de la BD antes de --confirmar.')
            return
        with transaction.atomic():
            workspace = Workspace.objects.filter(owner=user).first()
            if workspace and (CuentaContable.objects.filter(workspace=workspace).exists() or AsientoContable.objects.filter(workspace=workspace).exists()):
                raise CommandError('El usuario ya tiene un caso. Cree un usuario destinado al histórico para no mezclar registros.')
            if workspace is None: workspace = Workspace.objects.create(owner=user)
            for modelo in modelos:
                modelo.objects.filter(workspace__isnull=True).update(workspace=workspace)
        self.stdout.write(f'Asignados sin renumerar ni cambiar importes. Workspace {workspace.pk}')
