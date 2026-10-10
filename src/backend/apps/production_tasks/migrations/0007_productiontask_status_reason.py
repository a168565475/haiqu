from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("production_tasks", "0006_productiontaskproduct_packaging_method_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="productiontask",
            name="status_reason",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
