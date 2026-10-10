from django.db import models


class AssemblyReceiptSource(models.Model):
    receipt = models.OneToOneField('inventory.FinishedGoodsReceipt', primary_key=True,
        on_delete=models.PROTECT, related_name='assembly_source')
    schedule_product = models.ForeignKey('production_scheduling.ProductionScheduleProduct',
        on_delete=models.PROTECT, related_name='finished_receipt_sources')
    request_id = models.UUIDField(unique=True)
    payload_hash = models.CharField(max_length=64)
    receipt_date = models.DateField()
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = 'inventory_assembly_receipt_source'
        default_permissions = ()
        indexes = [models.Index(fields=['-receipt_date','receipt'], name='inv_assembly_receipt_date')]
