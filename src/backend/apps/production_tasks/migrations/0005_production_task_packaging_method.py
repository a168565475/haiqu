from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0004_production_task_fees"),
    ]

    operations = [
        migrations.AddField(
            model_name="productiontask",
            name="packaging_method_html",
            field=models.TextField(blank=True),
        ),
    ]
