import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0030_sampleproduct_item_number_snapshot_and_more"),
        ("material_catalog", "0003_catalog_warehouses_and_labels"),
    ]
    operations = [
        migrations.AddField(model_name="samplematerialissueline", name="material_catalog",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="sample_issue_lines", to="material_catalog.materialcatalog")),
        migrations.AddField(model_name="samplematerialissueline", name="material_selection_snapshot",
            field=models.JSONField(blank=True, default=dict)),
        migrations.AlterField(model_name="samplematerialissueline", name="raw_material",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="sample_material_issue_lines", to="products.rawmaterialinformation")),
        migrations.AddConstraint(model_name="samplematerialissueline", constraint=models.CheckConstraint(
            condition=models.Q(raw_material__isnull=False, material_catalog__isnull=True)
                | models.Q(raw_material__isnull=True, material_catalog__isnull=False),
            name="sample_issue_material_source_one")),
    ]
