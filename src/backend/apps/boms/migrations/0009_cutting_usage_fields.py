from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("boms", "0008_material_flow_constraints")]

    operations = [
        migrations.AddField(
            model_name="bomline", name="cutting_pieces_per_set",
            field=models.PositiveBigIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="bomline", name="fabric_meters_per_piece",
            field=models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="bomline", name="cutting_sets_per_product",
            field=models.PositiveBigIntegerField(null=True, blank=True),
        ),
        migrations.AddConstraint(
            model_name="bomline",
            constraint=models.CheckConstraint(
                condition=(models.Q(cutting_pieces_per_set__isnull=True, fabric_meters_per_piece__isnull=True,
                                    cutting_sets_per_product__isnull=True)
                    | models.Q(cutting_pieces_per_set__isnull=False, cutting_pieces_per_set__gt=0,
                               cutting_pieces_per_set__lt=100000000000000, fabric_meters_per_piece__isnull=False,
                               fabric_meters_per_piece__gt=0, cutting_sets_per_product__isnull=False,
                               cutting_sets_per_product__gt=0, cutting_sets_per_product__lt=100000000000000)),
                name="bom_cutting_usage_complete",
            ),
        ),
    ]
