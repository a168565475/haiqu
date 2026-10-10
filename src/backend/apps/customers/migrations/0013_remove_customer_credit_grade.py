from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0012_seed_ente_customer_regions"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="customeraccount",
            name="credit_grade_item",
        ),
    ]
