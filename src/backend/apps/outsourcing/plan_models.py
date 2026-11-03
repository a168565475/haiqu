"""总单收货凭证；只归总单部件，不与实际外发批次配对。"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class TubePlanReceipt(TimeStampedModel):
    order = models.ForeignKey('outsourcing.TubeOutsourcingOrder', on_delete=models.PROTECT, related_name='plan_receipts')
    receipt_number = models.CharField(max_length=50, unique=True)
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    receipt_date = models.DateField()
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT, related_name='outsourcing_plan_receipts')
    actor_employee = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT, related_name='outsourcing_plan_receipts')
    remark = models.TextField(blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'tube_plan_receipt'
        default_permissions = ()
        ordering = ['created_at', 'pk']

    def delete(self, *args, **kwargs):
        raise ValidationError('委外入库凭证必须保留，不支持直接删除。')


class TubePlanReceiptLine(TimeStampedModel):
    receipt = models.ForeignKey(TubePlanReceipt, on_delete=models.PROTECT, related_name='lines')
    order_line = models.ForeignKey('outsourcing.TubeOutsourcingLine', on_delete=models.PROTECT, related_name='plan_receipt_lines')
    received_quantity = models.PositiveBigIntegerField()
    zone = models.ForeignKey('inventory.WarehouseZone', on_delete=models.PROTECT, related_name='outsourcing_plan_receipt_lines')
    stock_movement = models.OneToOneField('inventory.PublicStockMovement', on_delete=models.PROTECT, related_name='outsourcing_plan_receipt_line')
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = 'tube_plan_receipt_line'
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['receipt', 'order_line'], name='tube_plan_receipt_line_unique'),
            models.CheckConstraint(condition=Q(received_quantity__gt=0, received_quantity__lte=99999999999999), name='tube_plan_receipt_qty_positive'),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError('委外入库明细必须保留，不支持直接删除。')


class TubePlanRecordCorrection(TimeStampedModel):
    """更正回执及原值；库存差额另记流水，不覆盖原库存事件。"""
    order = models.ForeignKey('outsourcing.TubeOutsourcingOrder', on_delete=models.PROTECT,
                              related_name='record_corrections')
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    record_kind = models.CharField(max_length=8, choices=[('DISPATCH', '外发'), ('RECEIPT', '入库')])
    record_id = models.UUIDField()
    operation = models.CharField(max_length=6, choices=[('UPDATE', '调整'), ('DELETE', '删除整次')])
    actor_employee = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT,
                                       related_name='outsourcing_plan_corrections')
    before_data = models.JSONField(default=dict)
    after_data = models.JSONField(default=dict)
    stock_movements = models.JSONField(default=list)

    class Meta:
        db_table = 'tube_plan_record_correction'
        default_permissions = ()
        ordering = ['created_at', 'pk']
        constraints = [
            models.CheckConstraint(condition=Q(record_kind__in=['DISPATCH', 'RECEIPT']),
                                   name='tube_correction_kind_valid'),
            models.CheckConstraint(condition=Q(operation__in=['UPDATE', 'DELETE']),
                                   name='tube_correction_operation_valid'),
        ]
