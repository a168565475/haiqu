"""D2管材外发保存与预留；与旧外发写入模型分开。"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class TubeSourceKind(models.TextChoices):
    RAW_PIPE = 'RAW_PIPE', '公共原管材'
    PUBLIC_SEMI = 'PUBLIC_SEMI', '公共未喷塑半成品'
    METAL = 'METAL', '厂内已加工件'


class TubeOutsourcingOrder(TimeStampedModel):
    order_number = models.CharField(max_length=50, unique=True)
    stock_mode = models.CharField(max_length=16, default='PUBLIC_V2')
    schedule_product = models.ForeignKey('production_scheduling.ProductionScheduleProduct', on_delete=models.PROTECT,
                                         related_name='tube_outsourcing_orders')
    product_line = models.ForeignKey('production_tasks.ProductionTaskProduct', on_delete=models.PROTECT,
                                     related_name='tube_outsourcing_orders')
    bom = models.ForeignKey('boms.Bom', on_delete=models.PROTECT, related_name='tube_outsourcing_orders')
    craft = models.ForeignKey('workshop_config.Craft', on_delete=models.PROTECT, related_name='tube_outsourcing_orders')
    source_kind = models.CharField(max_length=16, choices=TubeSourceKind.choices)
    zone = models.ForeignKey('inventory.WarehouseZone', null=True, blank=True, on_delete=models.PROTECT,
                             related_name='tube_outsourcing_orders')
    planned_dispatch_date = models.DateField()
    expected_return_date = models.DateField()
    status = models.CharField(max_length=24, default='PENDING_DISPATCH')
    remark = models.TextField(blank=True)
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    source_revision_hash = models.CharField(max_length=64)
    source_snapshot = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    created_by_employee = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT,
                                            related_name='created_tube_outsourcing_orders')
    updated_by_employee = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT,
                                            related_name='updated_tube_outsourcing_orders')

    class Meta:
        db_table = 'tube_outsourcing_order'
        default_permissions = ()
        ordering = ['-created_at', '-id']
        constraints = [
            models.CheckConstraint(condition=Q(stock_mode='PUBLIC_V2'), name='tube_order_public_mode'),
            models.CheckConstraint(condition=Q(source_kind__in=TubeSourceKind.values), name='tube_order_source_valid'),
            models.CheckConstraint(condition=Q(status__in=['PENDING_DISPATCH', 'PROCESSING', 'COMPLETED', 'CANCELLED']),
                                   name='tube_order_saved_status'),
            models.CheckConstraint(condition=Q(version__gt=0), name='tube_order_version_positive'),
            models.CheckConstraint(condition=(Q(source_kind='METAL', zone__isnull=True)
                | Q(source_kind__in=['RAW_PIPE', 'PUBLIC_SEMI'], zone__isnull=False)), name='tube_order_zone_shape'),
        ]
        indexes = [models.Index(fields=['product_line', 'source_kind', 'status'], name='tube_order_quota_idx')]

    def delete(self, *args, **kwargs):
        raise ValidationError('已保存管材外发单须保留，不支持直接删除。')


class TubeOutsourcingLine(TimeStampedModel):
    order = models.ForeignKey(TubeOutsourcingOrder, on_delete=models.PROTECT, related_name='lines')
    bom_line = models.ForeignKey('boms.BomLine', on_delete=models.PROTECT, related_name='tube_outsourcing_lines')
    component_identity = models.UUIDField()
    factory = models.ForeignKey('outsourcing.OutsourcingFactory', on_delete=models.PROTECT,
                                related_name='tube_outsourcing_lines')
    quantity = models.PositiveBigIntegerField()
    stock_quantity = models.PositiveBigIntegerField(null=True, blank=True)
    input_identity = models.JSONField(default=dict, blank=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = 'tube_outsourcing_line'
        default_permissions = ()
        ordering = ['order', 'created_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['order', 'component_identity'], name='tube_order_component_unique'),
            models.CheckConstraint(condition=Q(quantity__gt=0, quantity__lte=99999999999999), name='tube_line_quantity_valid'),
            models.CheckConstraint(condition=Q(stock_quantity__isnull=True) | Q(stock_quantity__gt=0),
                                   name='tube_line_stock_positive'),
        ]
        indexes = [models.Index(fields=['component_identity', 'order'], name='tube_line_component_idx')]

    def delete(self, *args, **kwargs):
        raise ValidationError('已保存管材外发明细须保留，不支持直接删除。')


class TubeOutsourcingAction(TimeStampedModel):
    """每次已成功的整单动作及原请求凭证；失败请求不留下业务记录。"""
    order = models.ForeignKey(TubeOutsourcingOrder, on_delete=models.PROTECT, related_name='actions')
    kind = models.CharField(max_length=12, choices=[('DISPATCH', '实际发出'), ('CANCEL', '待发取消')])
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    actual_dispatch_date = models.DateField(null=True, blank=True)
    remark = models.TextField(blank=True)
    actor_employee = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT,
                                       related_name='tube_outsourcing_actions')
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = 'tube_outsourcing_action'
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['order', 'kind'], name='tube_action_order_kind_unique'),
            models.CheckConstraint(condition=Q(kind__in=['DISPATCH', 'CANCEL']), name='tube_action_kind_valid'),
            models.CheckConstraint(condition=(Q(kind='DISPATCH', actual_dispatch_date__isnull=False)
                | Q(kind='CANCEL', actual_dispatch_date__isnull=True)), name='tube_action_date_shape'),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError('管材外发操作凭证须保留，不支持直接删除。')


class TubeOutsourcingReceipt(TimeStampedModel):
    """一单一次最终回货；全零也保留完整凭证。"""
    order = models.OneToOneField(TubeOutsourcingOrder, on_delete=models.PROTECT, related_name='final_receipt')
    receipt_number = models.CharField(max_length=50, unique=True)
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    receipt_date = models.DateField()
    warehouse = models.ForeignKey('inventory.Warehouse', null=True, blank=True, on_delete=models.PROTECT,
                                  related_name='tube_outsourcing_receipts')
    actor_employee = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT,
                                       related_name='tube_outsourcing_receipts')
    remark = models.TextField(blank=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = 'tube_outsourcing_receipt'
        default_permissions = ()

    def delete(self, *args, **kwargs):
        raise ValidationError('管材最终回货凭证须保留，不支持直接删除。')


class TubeOutsourcingReceiptLine(TimeStampedModel):
    receipt = models.ForeignKey(TubeOutsourcingReceipt, on_delete=models.PROTECT, related_name='lines')
    order_line = models.OneToOneField(TubeOutsourcingLine, on_delete=models.PROTECT, related_name='receipt_line')
    dispatched_quantity = models.PositiveBigIntegerField()
    received_quantity = models.PositiveBigIntegerField()
    shortage_quantity = models.PositiveBigIntegerField()
    shortage_reason = models.TextField(blank=True)
    zone = models.ForeignKey('inventory.WarehouseZone', null=True, blank=True, on_delete=models.PROTECT,
                             related_name='tube_outsourcing_receipt_lines')
    stock_movement = models.OneToOneField('inventory.PublicStockMovement', null=True, blank=True,
                                         on_delete=models.PROTECT, related_name='tube_outsourcing_receipt_line')
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = 'tube_outsourcing_receipt_line'
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=Q(dispatched_quantity__gt=0,
                dispatched_quantity__lte=99999999999999, received_quantity__gte=0,
                received_quantity__lte=models.F('dispatched_quantity')), name='tube_receipt_quantity_valid'),
            models.CheckConstraint(condition=Q(shortage_quantity=models.F('dispatched_quantity')
                - models.F('received_quantity')), name='tube_receipt_shortage_valid'),
            models.CheckConstraint(condition=Q(shortage_quantity=0) | ~Q(shortage_reason=''),
                                   name='tube_receipt_shortage_reason'),
            models.CheckConstraint(condition=(Q(received_quantity=0, zone__isnull=True, stock_movement__isnull=True)
                | Q(received_quantity__gt=0, zone__isnull=False, stock_movement__isnull=False)),
                name='tube_receipt_stock_shape'),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError('管材最终回货明细须保留，不支持直接删除。')
