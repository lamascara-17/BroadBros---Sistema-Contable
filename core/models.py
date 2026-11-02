"""
Modelos del Sistema Contable.

Define tres entidades principales:
- CuentaContable: Catálogo de cuentas con su clasificación (Activo, Pasivo, etc.)
- AsientoContable: Cabecera de cada asiento con fecha y descripción
- Movimiento: Líneas de detalle (Debe/Haber) vinculadas a un asiento y una cuenta
"""
from django.db import models
from decimal import Decimal
from django.conf import settings
import uuid
from .workspaces import WorkspaceManager, MovimientoManager, workspace_actual


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class RespaldoCaso(models.Model):
    workspace = models.ForeignKey(Workspace, null=True, on_delete=models.PROTECT, default=workspace_actual)
    datos = models.JSONField()
    catalogo = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = WorkspaceManager()



class CuentaContable(models.Model):
    """
    Representa una cuenta del plan contable.
    Cada cuenta tiene un código único, nombre y tipo que determina
    su comportamiento en los reportes financieros.
    """
    TIPO_CHOICES = [
        ('activo', 'Activo'),
        ('pasivo', 'Pasivo'),
        ('patrimonio', 'Patrimonio'),
        ('ingreso', 'Ingreso'),
        ('gasto', 'Gasto'),
    ]

    # Subcategoría para clasificar cuentas en el Estado de Resultados
    SUBCATEGORIA_CHOICES = [
        ('', 'General'),
        ('costo_ventas', 'Costo de Ventas'),
        ('gasto_operativo', 'Gasto Operativo'),
        ('gasto_financiero', 'Gasto Financiero'),
        ('otro_ingreso', 'Otro Ingreso'),
        ('otro_gasto', 'Otro Gasto'),
        ('impuesto_ganancias', 'Impuesto a las ganancias'),
        ('activo_corriente', 'Activo corriente'),
        ('activo_no_corriente', 'Activo no corriente'),
        ('pasivo_corriente', 'Pasivo corriente'),
        ('pasivo_no_corriente', 'Pasivo no corriente'),
    ]

    workspace = models.ForeignKey(Workspace, null=True, on_delete=models.PROTECT, default=workspace_actual)
    objects = WorkspaceManager()
    codigo = models.CharField(max_length=20, verbose_name='Código')
    nombre = models.CharField(max_length=200, verbose_name='Nombre')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, verbose_name='Tipo')
    subcategoria = models.CharField(
        max_length=20,
        choices=SUBCATEGORIA_CHOICES,
        blank=True,
        default='',
        verbose_name='Subcategoría financiera'
    )

    class Meta:
        ordering = ['codigo']
        constraints = [models.UniqueConstraint(fields=['workspace', 'codigo'], name='cuenta_workspace_codigo')]
        verbose_name = 'Cuenta Contable'
        verbose_name_plural = 'Cuentas Contables'

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

    @property
    def naturaleza_deudora(self):
        """Las cuentas de Activo y Gasto tienen naturaleza deudora."""
        return self.tipo in ('activo', 'gasto')


class AsientoContable(models.Model):
    """
    Cabecera de un asiento contable.
    Agrupa uno o más movimientos que deben estar balanceados (Debe == Haber).
    """
    workspace = models.ForeignKey(Workspace, null=True, on_delete=models.PROTECT, default=workspace_actual)
    objects = WorkspaceManager()
    fuente_importacion = models.TextField(blank=True, default='')
    fecha = models.DateField(verbose_name='Fecha')
    fecha_cierre_ejercicio = models.DateField(null=True, blank=True, verbose_name='Fecha de cierre del ejercicio')
    CLASE_CHOICES=[('operacion','Operación o ajuste'),('apertura','Saldo de apertura'),('cierre','Cierre de resultados')]
    FLUJO_CHOICES=[('pendiente','Pendiente de clasificar'),('operacion','Operación'),('inversion','Inversión'),('financiacion','Financiación')]
    clase=models.CharField(max_length=12,choices=CLASE_CHOICES,default='operacion')
    flujo_efectivo=models.CharField(max_length=12,choices=FLUJO_CHOICES,default='pendiente')
    descripcion = models.TextField(blank=True, default='', verbose_name='Descripción')
    observaciones_importacion = models.TextField(blank=True, default='', verbose_name='Datos pendientes de la importación')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha', 'id'] 
        verbose_name = 'Asiento Contable'
        verbose_name_plural = 'Asientos Contables'

    def __str__(self):
        return f"Asiento #{self.id} — {self.fecha}"

    @property
    def total_debe(self):
        """Suma total de movimientos al Debe."""
        if 'movimientos' in getattr(self,'_prefetched_objects_cache',{}):
            return sum((m.monto for m in self.movimientos.all() if m.tipo=='debe'),Decimal('0'))
        return self.movimientos.filter(tipo='debe').aggregate(
            total=models.Sum('monto'))['total'] or Decimal('0')

    @property
    def total_haber(self):
        """Suma total de movimientos al Haber."""
        if 'movimientos' in getattr(self,'_prefetched_objects_cache',{}):
            return sum((m.monto for m in self.movimientos.all() if m.tipo=='haber'),Decimal('0'))
        return self.movimientos.filter(tipo='haber').aggregate(
            total=models.Sum('monto'))['total'] or Decimal('0')

    @property
    def esta_balanceado(self):
        """Verifica que el asiento esté cuadrado."""
        return self.total_debe == self.total_haber


class Movimiento(models.Model):
    """
    Línea de detalle de un asiento contable.
    Cada movimiento afecta una cuenta específica al Debe o al Haber.
    """
    TIPO_CHOICES = [
        ('debe', 'Debe'),
        ('haber', 'Haber'),
    ]

    objects = MovimientoManager()

    asiento = models.ForeignKey(
        AsientoContable,
        on_delete=models.CASCADE,
        related_name='movimientos',
        verbose_name='Asiento'
    )
    cuenta = models.ForeignKey(
        CuentaContable,
        on_delete=models.PROTECT,
        related_name='movimientos',
        verbose_name='Cuenta'
    )
    tipo = models.CharField(max_length=5, choices=TIPO_CHOICES, verbose_name='Tipo')
    monto = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Monto')

    class Meta:
        verbose_name = 'Movimiento'
        verbose_name_plural = 'Movimientos'

    def __str__(self):
        return f"{self.cuenta} — {self.get_tipo_display()}: S/ {self.monto:,.2f}"
    #a


class FinancialRatioPeriod(models.Model):
    """Datos externos independientes del ejercicio contable activo."""
    workspace = models.ForeignKey(Workspace, null=True, on_delete=models.PROTECT, default=workspace_actual)
    objects = WorkspaceManager()
    ticker = models.CharField(max_length=12)
    year = models.PositiveIntegerField()
    name = models.CharField(max_length=120)
    industry = models.CharField(max_length=160, blank=True)
    currency = models.CharField(max_length=3, default='USD')
    period_start = models.DateField()
    period_end = models.DateField()
    previous_end = models.DateField()
    values = models.JSONField(default=dict)
    source_url = models.URLField(max_length=600, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace', 'ticker', 'year'], name='ratio_company_year_unique')]
