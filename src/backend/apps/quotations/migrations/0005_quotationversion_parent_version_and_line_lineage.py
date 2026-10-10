import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quotations", "0004_quotationcontainerconfig_quotationlinepackaging_and_more")]

    operations = [
        migrations.AddField(
            model_name="quotationversion",
            name="parent_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="child_versions",
                to="quotations.quotationversion",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.AddField(
                model_name="quotationline",
                name="lineage_id",
                field=models.UUIDField(blank=True, db_index=True, editable=False, null=True),
            )],
            state_operations=[migrations.AddField(
                model_name="quotationline",
                name="lineage_id",
                field=models.UUIDField(blank=True, db_index=True, default=uuid.uuid4, editable=False, null=True),
            )],
        ),
    ]
