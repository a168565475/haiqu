from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workshop_config", "0009_remove_operation_required_quantity_per_product")]

    operations = [
        migrations.AlterField(
            model_name="craft",
            name="outsourcing_code",
            field=models.CharField(blank=True, choices=[
                ("POWDER_COATING", "喷塑"), ("SCREEN_PRINTING", "丝印"),
                ("EMBROIDERY", "刺绣"), ("CUTTING", "裁剪"), ("SEWING", "车缝"),
            ], max_length=30, null=True),
        ),
    ]
