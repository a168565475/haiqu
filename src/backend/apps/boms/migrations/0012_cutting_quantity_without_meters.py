from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("boms", "0011_product_review_snapshots")]

    operations = [
        migrations.RemoveConstraint(model_name="bomline", name="bom_cutting_usage_complete"),
        migrations.AddConstraint(
            model_name="bomline",
            constraint=models.CheckConstraint(
                condition=((models.Q(cutting_pieces_per_set__isnull=True, cutting_sets_per_product__isnull=True)
                    | models.Q(cutting_pieces_per_set__isnull=False, cutting_pieces_per_set__gt=0,
                               cutting_pieces_per_set__lt=100000000000000, cutting_sets_per_product__isnull=False,
                               cutting_sets_per_product__gt=0, cutting_sets_per_product__lt=100000000000000))
                    & (models.Q(fabric_meters_per_piece__isnull=True) | models.Q(fabric_meters_per_piece__gt=0))),
                name="bom_cutting_usage_complete",
            ),
        ),
    ]
