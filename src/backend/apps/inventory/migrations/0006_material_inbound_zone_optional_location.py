import django.db.models.deletion
from django.db import migrations, models


def backfill_material_zones(apps, schema_editor):
    inbound_line_model = apps.get_model("inventory", "MaterialInboundLine")
    for line in inbound_line_model.objects.select_related("location").iterator(chunk_size=500):
        line.zone_id = line.location.zone_id
        line.save(update_fields=["zone_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0005_alter_materialinbound_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="materialinboundline",
            name="zone",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="material_inbound_lines",
                to="inventory.warehousezone",
            ),
        ),
        migrations.RunPython(backfill_material_zones, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="materialinboundline",
            name="zone",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="material_inbound_lines",
                to="inventory.warehousezone",
            ),
        ),
        migrations.AlterField(
            model_name="materialinboundline",
            name="location",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="material_inbound_lines",
                to="inventory.warehouselocation",
            ),
        ),
        migrations.AddIndex(
            model_name="materialinboundline",
            index=models.Index(fields=["zone", "created_at"], name="inv_mat_zone_idx"),
        ),
    ]
