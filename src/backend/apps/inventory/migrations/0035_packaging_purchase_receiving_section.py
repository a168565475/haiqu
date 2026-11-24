from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0034_purchase_inbound_material_section_updated")]

    operations = [
        migrations.AlterField(
            model_name="materialinbound",
            name="material_section",
            field=models.CharField(
                blank=True, choices=[("A", "A区"), ("B", "B区"), ("C", "C区"), ("D", "包材")],
                db_default="", default="", editable=False, max_length=1,
            ),
        ),
    ]
