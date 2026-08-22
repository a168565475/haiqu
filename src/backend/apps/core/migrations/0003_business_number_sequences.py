from django.db import migrations


FORWARD_SQL = """
CREATE SEQUENCE haiqu_customer_number_seq AS bigint START WITH 1 INCREMENT BY 1 CACHE 1;
CREATE SEQUENCE haiqu_inquiry_number_seq AS bigint START WITH 1 INCREMENT BY 1 CACHE 1;
CREATE SEQUENCE haiqu_quotation_number_seq AS bigint START WITH 1 INCREMENT BY 1 CACHE 1;
CREATE SEQUENCE haiqu_sample_number_seq AS bigint START WITH 1 INCREMENT BY 1 CACHE 1;
"""


REVERSE_SQL = """
DROP SEQUENCE IF EXISTS haiqu_sample_number_seq;
DROP SEQUENCE IF EXISTS haiqu_quotation_number_seq;
DROP SEQUENCE IF EXISTS haiqu_inquiry_number_seq;
DROP SEQUENCE IF EXISTS haiqu_customer_number_seq;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_database_integrity_triggers"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
