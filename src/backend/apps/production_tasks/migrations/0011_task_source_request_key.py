from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0010_product_sales_source_line"),
    ]

    operations = [
        migrations.AddField(
            model_name="productiontask",
            name="source_request_key",
            field=models.UUIDField(blank=True, null=True, unique=True),
        ),
    ]
