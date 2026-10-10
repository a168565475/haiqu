from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("boms", "0005_alter_bom_options_bom_confirmation_reason_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="bom",
            name="quantity_difference_reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]
