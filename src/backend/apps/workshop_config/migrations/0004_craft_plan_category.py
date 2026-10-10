from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("workshop_config", "0003_fixed_workshop_constraints")]

    operations = [
        migrations.AddField(
            model_name="craft",
            name="plan_category",
            field=models.CharField(
                blank=True,
                choices=[
                    ("METAL", "金工计划"),
                    ("CUTTING", "裁剪计划"),
                    ("SEWING", "车缝计划"),
                    ("ASSEMBLY", "装配计划"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="craft",
            constraint=models.CheckConstraint(
                condition=Q(plan_category__isnull=True) | Q(craft_type="INTERNAL"),
                name="workshop_craft_plan_internal",
            ),
        ),
        migrations.AddConstraint(
            model_name="craft",
            constraint=models.UniqueConstraint(
                fields=("plan_category",),
                condition=Q(plan_category__isnull=False),
                name="workshop_craft_plan_unique",
            ),
        ),
    ]
