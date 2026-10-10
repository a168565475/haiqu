from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0011_semifinishedstockbalance_semifinishedstockmovement_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="materialstockmovement",
            name="inv_mat_movement_source_uniq",
        ),
        migrations.AddConstraint(
            model_name="materialstockmovement",
            constraint=models.UniqueConstraint(
                fields=("source_type", "source_line_id", "direction", "balance"),
                name="inv_mat_movement_source_uniq",
            ),
        ),
    ]
