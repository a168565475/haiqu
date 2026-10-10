import uuid

import apps.core.models
import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0016_sample_inventory_outbound"),
    ]

    operations = [
        migrations.CreateModel(
            name="SampleInventoryLoan",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "loan_number",
                    models.CharField(
                        max_length=50,
                        unique=True,
                        validators=[apps.core.models.uppercase_code_validator],
                    ),
                ),
                ("operated_at", models.DateTimeField()),
                (
                    "operated_by_employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sample_inventory_loans",
                        to="organizations.employee",
                    ),
                ),
            ],
            options={
                "db_table": "sample_inventory_loan",
                "ordering": ["-operated_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="SampleInventoryLoanLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("loan_quantity", models.PositiveIntegerField()),
                ("borrower_name", models.CharField(max_length=150)),
                ("purpose_note", models.CharField(max_length=500)),
                (
                    "inventory_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="loan_lines",
                        to="samples.sampleinventoryline",
                    ),
                ),
                (
                    "loan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lines",
                        to="samples.sampleinventoryloan",
                    ),
                ),
            ],
            options={
                "db_table": "sample_inventory_loan_line",
                "ordering": ["-loan__operated_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryloan",
            constraint=models.CheckConstraint(
                condition=models.Q(("loan_number", django.db.models.functions.text.Upper(models.F("loan_number")))),
                name="sample_loan_number_upper",
            ),
        ),
        migrations.AddIndex(
            model_name="sampleinventoryloan",
            index=models.Index(fields=["-operated_at", "-id"], name="sample_loan_time_idx"),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryloanline",
            constraint=models.UniqueConstraint(
                fields=("loan", "inventory_line"),
                name="sample_loan_inventory_line_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryloanline",
            constraint=models.CheckConstraint(
                condition=models.Q(("loan_quantity__gt", 0)),
                name="sample_loan_quantity_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryloanline",
            constraint=models.CheckConstraint(
                condition=~models.Q(("borrower_name", "")),
                name="sample_loan_borrower_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryloanline",
            constraint=models.CheckConstraint(
                condition=~models.Q(("purpose_note", "")),
                name="sample_loan_purpose_required",
            ),
        ),
        migrations.AddIndex(
            model_name="sampleinventoryloanline",
            index=models.Index(fields=["borrower_name", "id"], name="sample_loan_borrower_idx"),
        ),
        migrations.AddIndex(
            model_name="sampleinventoryloanline",
            index=models.Index(fields=["inventory_line", "id"], name="sample_loan_inventory_idx"),
        ),
    ]
