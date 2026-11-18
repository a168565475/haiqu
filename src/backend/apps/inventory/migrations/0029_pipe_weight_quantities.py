from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0028_material_transfer")]

    operations = [
        migrations.AddField(
            model_name="materialinboundline",
            name="bar_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name="materialinboundline",
            name="received_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="materialinboundline",
            name="accepted_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="materialinboundline",
            name="return_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="materialstockbalance",
            name="bar_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name="materialstockbalance",
            name="weight_quantity",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="materialstockmovement",
            name="weight_quantity",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="materialstockmovement",
            name="before_weight_quantity",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="materialstockmovement",
            name="after_weight_quantity",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="publicstockbalance",
            name="bar_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name="publicstockbalance",
            name="weight_quantity",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="publicstockmovement",
            name="weight_quantity",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="publicstockmovement",
            name="before_weight_quantity",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="publicstockmovement",
            name="after_weight_quantity",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
    ]
