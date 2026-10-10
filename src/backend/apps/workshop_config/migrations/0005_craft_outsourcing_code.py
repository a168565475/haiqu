from django.db import migrations, models
import django.db.models


class Migration(migrations.Migration):
    dependencies = [
        ("workshop_config", "0004_craft_plan_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="craft",
            name="outsourcing_code",
            field=models.CharField(
                blank=True,
                choices=[
                    ("POWDER_COATING", "喷塑"),
                    ("SCREEN_PRINTING", "丝印"),
                    ("CUTTING", "裁剪"),
                    ("SEWING", "车缝"),
                ],
                max_length=30,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="craft",
            constraint=models.UniqueConstraint(
                condition=django.db.models.Q(("outsourcing_code__isnull", False)),
                fields=("outsourcing_code",),
                name="workshop_craft_outsourcing_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="craft",
            constraint=models.CheckConstraint(
                condition=(
                    django.db.models.Q(("outsourcing_code__isnull", True))
                    | django.db.models.Q(("craft_type", "EXTERNAL"))
                ),
                name="workshop_craft_outsourcing_external",
            ),
        ),
    ]
