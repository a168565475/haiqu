import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("samples", "0026_sample_parameter_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="SampleMaterialIssue",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("PENDING_CONFIRMATION", "待仓库确认"), ("ISSUED", "已领料")], default="PENDING_CONFIRMATION", max_length=30)),
                ("version", models.PositiveIntegerField(default=1)),
                ("client_request_id", models.UUIDField(blank=True, null=True, unique=True)),
                ("confirmation_request_id", models.UUIDField(blank=True, null=True, unique=True)),
                ("initiated_at", models.DateTimeField(blank=True, null=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.TextField(blank=True)),
                ("confirmed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_sample_material_issues", to="organizations.employee")),
                ("initiated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="initiated_sample_material_issues", to="organizations.employee")),
                ("material_request", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="issue", to="samples.samplematerialrequest")),
            ],
            options={"db_table": "sample_material_issue"},
        ),
        migrations.CreateModel(
            name="SampleMaterialIssueLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("line_key", models.UUIDField()),
                ("category", models.CharField(max_length=30)),
                ("name_snapshot", models.CharField(max_length=500)),
                ("specification_snapshot", models.CharField(blank=True, max_length=500)),
                ("material_snapshot", models.CharField(blank=True, max_length=500)),
                ("color_snapshot", models.CharField(blank=True, max_length=500)),
                ("requested_quantity", models.DecimalField(decimal_places=4, max_digits=18)),
                ("warehouse_quantity", models.DecimalField(decimal_places=4, default=0, max_digits=18)),
                ("arrived_quantity", models.DecimalField(decimal_places=4, default=0, max_digits=18)),
                ("available_quantity", models.DecimalField(decimal_places=4, default=0, max_digits=18)),
                ("issued_quantity", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("shortage_quantity", models.DecimalField(decimal_places=4, default=0, max_digits=18)),
                ("issue", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="samples.samplematerialissue")),
                ("raw_material", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sample_material_issue_lines", to="products.rawmaterialinformation")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sample_material_issue_lines", to="reference_data.productionunit")),
            ],
            options={"db_table": "sample_material_issue_line", "ordering": ["issue", "id"]},
        ),
        migrations.AddConstraint(
            model_name="samplematerialissue",
            constraint=models.CheckConstraint(condition=models.Q(status__in=["PENDING_CONFIRMATION", "ISSUED"]), name="sample_issue_status_valid"),
        ),
        migrations.AddConstraint(
            model_name="samplematerialissue",
            constraint=models.CheckConstraint(condition=models.Q(version__gt=0), name="sample_issue_version_positive"),
        ),
        migrations.AddConstraint(
            model_name="samplematerialissueline",
            constraint=models.UniqueConstraint(fields=("issue", "line_key"), name="sample_issue_line_key_uniq"),
        ),
        migrations.AddConstraint(
            model_name="samplematerialissueline",
            constraint=models.CheckConstraint(condition=models.Q(requested_quantity__gt=0), name="sample_issue_line_request_positive"),
        ),
        migrations.AddConstraint(
            model_name="samplematerialissueline",
            constraint=models.CheckConstraint(condition=models.Q(warehouse_quantity__gte=0), name="sample_issue_line_warehouse_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="samplematerialissueline",
            constraint=models.CheckConstraint(condition=models.Q(arrived_quantity__gte=0), name="sample_issue_line_arrived_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="samplematerialissueline",
            constraint=models.CheckConstraint(condition=models.Q(available_quantity__gte=0), name="sample_issue_line_available_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="samplematerialissueline",
            constraint=models.CheckConstraint(condition=models.Q(shortage_quantity__gte=0), name="sample_issue_line_shortage_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="samplematerialissueline",
            constraint=models.CheckConstraint(condition=models.Q(issued_quantity__isnull=True) | models.Q(issued_quantity__gte=0), name="sample_issue_line_issued_nonnegative"),
        ),
    ]
