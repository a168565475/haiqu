from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("outsourcing", "0005_material_flow_reconciliation")]

    operations = [
        migrations.RemoveConstraint(model_name="outsourcingorder", name="outs_order_status_valid"),
        migrations.AlterField(
            model_name="outsourcingorder", name="status",
            field=models.CharField(max_length=30, default="PENDING_DISPATCH", choices=[
                ("PENDING_DISPATCH", "待外发"), ("PROCESSING", "加工中"), ("PARTIAL_RETURN", "部分回货"),
                ("CLOSED", "已结清"), ("COMPLETED", "已完成"), ("CANCELLED", "已取消")]),
        ),
        migrations.AddConstraint(
            model_name="outsourcingorder",
            constraint=models.CheckConstraint(condition=models.Q(status__in=[
                "PENDING_DISPATCH", "PROCESSING", "PARTIAL_RETURN", "CLOSED", "COMPLETED", "CANCELLED"]),
                name="outs_order_status_valid"),
        ),
    ]
