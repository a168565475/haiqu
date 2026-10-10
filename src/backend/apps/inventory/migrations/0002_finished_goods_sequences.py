from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_finished_goods_receipt_seq START WITH 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_finished_goods_receipt_seq;",
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_finished_goods_outbound_seq START WITH 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_finished_goods_outbound_seq;",
        ),
    ]
