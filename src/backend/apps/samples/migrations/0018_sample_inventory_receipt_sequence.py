from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0017_sample_inventory_loan"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_sample_inventory_receipt_seq START WITH 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_sample_inventory_receipt_seq;",
        ),
    ]
