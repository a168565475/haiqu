from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("material_catalog", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="materialcatalog",
            name="mat_catalog_template_valid",
        ),
        migrations.AlterField(
            model_name="materialcatalog",
            name="template_key",
            field=models.CharField(
                choices=[
                    ("TUBE", "管材"), ("FABRIC", "面料"), ("HARDWARE", "五金"),
                    ("PLASTIC", "塑料件"), ("CARTON", "纸箱"), ("BAG", "塑料袋"),
                    ("PACKAGING_GENERAL", "通用包材"), ("TAPE", "带类"), ("COTTON", "棉类"),
                    ("AUXILIARY_GENERAL", "通用辅料"), ("FABRIC_SEMI", "委外布面"),
                ],
                max_length=30,
            ),
        ),
        migrations.AddConstraint(
            model_name="materialcatalog",
            constraint=models.CheckConstraint(
                condition=(models.Q(category_key="TUBE", template_key="TUBE")
                    | models.Q(category_key="FABRIC", template_key="FABRIC")
                    | models.Q(category_key="HARDWARE", template_key="HARDWARE")
                    | models.Q(category_key="PLASTIC", template_key="PLASTIC")
                    | models.Q(category_key="PACKAGING", template_key__in=["CARTON", "BAG", "PACKAGING_GENERAL"])
                    | models.Q(category_key="AUXILIARY", template_key__in=["TAPE", "COTTON", "AUXILIARY_GENERAL"])
                    | models.Q(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI")),
                name="mat_catalog_template_valid",
            ),
        ),
    ]
