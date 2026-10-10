from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workshop_reporting", "0011_wageschemeline_production_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="workreportline",
            name="actual_usage_snapshot",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True),
        ),
        migrations.AddField(
            model_name="workreportline",
            name="actual_usage_unit_snapshot",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
