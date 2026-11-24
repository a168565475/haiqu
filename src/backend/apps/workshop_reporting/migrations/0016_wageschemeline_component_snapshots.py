from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workshop_reporting", "0015_alter_workreportline_employee_name_snapshot_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="wageschemeline",
            name="bom_component_kind_snapshot",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="wageschemeline",
            name="bom_parts_per_product_snapshot",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="wageschemeline",
            name="bom_pieces_per_part_snapshot",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
