"""Las fixtures históricas se construyen con privilegio explícito, no público."""
from django.test import TestCase as DjangoTestCase, SimpleTestCase as DjangoSimpleTestCase
from .workspaces import acceso_administrativo


class AdministrativeFixtures:
    @classmethod
    def setUpClass(cls):
        contexto = acceso_administrativo()
        contexto.__enter__()
        cls.addClassCleanup(contexto.__exit__, None, None, None)
        super().setUpClass()


class AdministrativeTestCase(AdministrativeFixtures, DjangoTestCase):
    pass


class AdministrativeSimpleTestCase(AdministrativeFixtures, DjangoSimpleTestCase):
    pass
