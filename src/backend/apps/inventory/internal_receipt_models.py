"""厂内入库原单与明细。只保存已确认记录，不建立第二套库存余额。"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Floor

from apps.core.models import TimeStampedModel


class InternalReceiptQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError('已确认入库记录不允许批量删除，须保留来源及库存流水。')


class InternalSemiFinishedReceipt(TimeStampedModel):
    objects = InternalReceiptQuerySet.as_manager()
    receipt_number = models.CharField(max_length=50, unique=True)
    request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    schedule_product = models.ForeignKey('production_scheduling.ProductionScheduleProduct',
                                         on_delete=models.PROTECT, related_name='internal_receipts')
    completed_craft = models.ForeignKey('workshop_config.Craft', on_delete=models.PROTECT,
                                       related_name='internal_semi_receipts')
    plan_category = models.CharField(max_length=20, choices=[('METAL','金工'),('SEWING','车缝')])
    receipt_date = models.DateField()
    zone = models.ForeignKey('inventory.WarehouseZone', on_delete=models.PROTECT,
                            related_name='internal_semi_receipts')
    actor_employee = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT,
                                      related_name='internal_semi_receipts')
    source_revision_hash = models.CharField(max_length=64)
    source_snapshot = models.JSONField()
    remark = models.TextField(blank=True)

    class Meta:
        db_table = 'inventory_internal_semi_receipt'
        ordering = ['-receipt_date','-created_at','-id']
        default_permissions = ('add','view')
        constraints = [models.CheckConstraint(condition=Q(plan_category__in=['METAL','SEWING']),
                                               name='inv_internal_receipt_stage')]
        indexes = [models.Index(fields=['schedule_product','plan_category'],name='inv_int_receipt_plan'),
                   models.Index(fields=['-receipt_date','-id'],name='inv_int_receipt_date')]

    def delete(self, *args, **kwargs):
        raise ValidationError('已确认入库记录不允许直接删除，须保留来源及库存流水。')


class InternalSemiFinishedReceiptLine(TimeStampedModel):
    objects = InternalReceiptQuerySet.as_manager()
    receipt = models.ForeignKey(InternalSemiFinishedReceipt, on_delete=models.PROTECT, related_name='lines')
    bom_line = models.ForeignKey('boms.BomLine', on_delete=models.PROTECT, related_name='internal_receipt_lines')
    component_identity = models.UUIDField()
    unit = models.ForeignKey('reference_data.ProductionUnit', on_delete=models.PROTECT,
                            related_name='internal_receipt_lines')
    # 材料需求是订单级汇总；不关联采购批次，前端也不选择领料批次。
    input_requirement = models.ForeignKey('material_issues.OrderMaterialRequirement',
                                         on_delete=models.PROTECT, related_name='internal_receipt_lines')
    input_unit_name = models.CharField(max_length=10, choices=[('支','支'),('米','米')])
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    input_per_output = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    input_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    required_quantity_snapshot = models.DecimalField(max_digits=18, decimal_places=4)
    received_before = models.DecimalField(max_digits=18, decimal_places=4)
    received_after = models.DecimalField(max_digits=18, decimal_places=4)
    # 强制一条实际入库明细对应一条公共库存流水，不另建余额字段。
    stock_movement = models.OneToOneField('inventory.PublicStockMovement', on_delete=models.PROTECT,
                                        related_name='internal_receipt_line')
    attribute_snapshot = models.JSONField()
    input_snapshot = models.JSONField()

    class Meta:
        db_table = 'inventory_internal_semi_receipt_line'
        ordering = ['created_at','id']
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['receipt','component_identity'],name='inv_int_receipt_component'),
            models.CheckConstraint(condition=Q(quantity__gt=0,quantity=Floor(F('quantity')),
                                               required_quantity_snapshot__gt=0,
                                               required_quantity_snapshot=Floor(F('required_quantity_snapshot')),
                                               received_before__gte=0,received_before=Floor(F('received_before')),
                                               received_after=F('received_before')+F('quantity'),
                                               received_after__lte=F('required_quantity_snapshot')),
                                   name='inv_int_receipt_quantities'),
            models.CheckConstraint(condition=Q(input_per_output__isnull=False,input_quantity__isnull=False,
                                               input_per_output__gt=0,input_quantity__gt=0,
                                               input_quantity=F('quantity')*F('input_per_output'))
                                               | Q(input_unit_name='米',input_per_output__isnull=True,input_quantity__isnull=True),
                                   name='inv_int_receipt_input'),
            models.CheckConstraint(condition=Q(input_unit_name='米') | Q(input_unit_name='支',input_per_output=1),
                                   name='inv_int_receipt_input_unit'),
        ]
        indexes = [models.Index(fields=['component_identity','receipt'],name='inv_int_receipt_part'),
                   models.Index(fields=['input_requirement','receipt'],name='inv_int_receipt_input_use')]

    def delete(self, *args, **kwargs):
        raise ValidationError('已确认入库明细不允许直接删除，须保留投入及库存流水。')
