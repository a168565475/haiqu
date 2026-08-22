from django.contrib.postgres.operations import BtreeGistExtension, TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    # PostgreSQL 专用索引与排斥约束在业务表建表时就会使用这些扩展。
    run_before = [
        ("reference_data", "0001_initial"),
        ("organizations", "0001_initial"),
        ("files", "0001_initial"),
        ("workflow", "0001_initial"),
        ("customers", "0001_initial"),
        ("inquiries", "0001_initial"),
        ("quotations", "0001_initial"),
        ("samples", "0001_initial"),
        ("crm", "0001_initial"),
        ("audit", "0001_initial"),
        ("imports", "0001_initial"),
        ("preferences", "0001_initial"),
    ]

    operations = [
        BtreeGistExtension(),
        TrigramExtension(),
    ]
