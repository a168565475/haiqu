from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0019_sample_inventory_outbound_sequence"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_sample_inventory_loan_seq START WITH 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_sample_inventory_loan_seq;",
        ),
    ]
