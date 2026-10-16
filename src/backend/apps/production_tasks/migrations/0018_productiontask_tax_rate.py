from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0017_merge_customer_and_product_snapshots"),
    ]

    operations = [
        migrations.AddField(
            model_name="productiontask",
            name="tax_rate",
            field=models.PositiveSmallIntegerField(blank=True, null=True, choices=[(3, "3%"), (5, "5%"), (7, "7%")]),
        ),
        # 历史含税单未记录税率，保留为空，在下一次生产确认时补填。
        migrations.AddConstraint(
            model_name="productiontask",
            constraint=models.CheckConstraint(
                condition=models.Q(tax_rate__isnull=True) | models.Q(includes_tax=True, tax_rate__in=[3, 5, 7]),
                name="prod_task_tax_rate_valid",
            ),
        ),
    ]
