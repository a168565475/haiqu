# Generated for SAM-02 样品详情与编辑。

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0001_initial"),
        ("samples", "0003_sam01_sample_type_and_statuses"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="samplerequest",
            name="sample_request_one_source_max",
        ),
        migrations.AddField(
            model_name="samplerequest",
            name="expected_received_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="samplerequest",
            name="expected_shipped_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="SampleCollaborator",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sample_collaborator_links", to="organizations.employee")),
                ("sample_request", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="collaborator_links", to="samples.samplerequest")),
            ],
            options={"db_table": "sample_collaborator"},
        ),
        migrations.AddConstraint(
            model_name="samplecollaborator",
            constraint=models.UniqueConstraint(fields=("sample_request", "employee"), name="sample_collaborator_unique"),
        ),
    ]
