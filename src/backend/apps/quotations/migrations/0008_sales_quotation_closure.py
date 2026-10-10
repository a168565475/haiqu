import uuid

import django.db.models.deletion
from django.db import migrations, models

import apps.core.models


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0007_restore_default_customer_tags"),
        ("files", "0002_initial"),
        ("quotations", "0007_quotation_product_image_and_simulated_dispatch"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuotationPriceBasis",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("label", models.CharField(max_length=120)),
                ("incoterm_code", models.CharField(max_length=20, validators=[apps.core.models.uppercase_code_validator])),
                ("named_place", models.CharField(max_length=180)),
                ("currency_code", models.CharField(max_length=3, validators=[apps.core.models.currency_code_validator])),
                ("is_default", models.BooleanField(default=False)),
                ("sort_order", models.PositiveSmallIntegerField(default=1)),
                ("notes", models.TextField(blank=True)),
                ("quotation_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="price_bases", to="quotations.quotationversion")),
            ],
            options={"db_table": "quotation_price_basis", "ordering": ["quotation_version", "sort_order", "id"]},
        ),
        migrations.CreateModel(
            name="QuotationLinePrice",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("unit_price", models.DecimalField(decimal_places=4, max_digits=18)),
                ("surcharge_note", models.CharField(blank=True, max_length=500)),
                ("is_manual_override", models.BooleanField(default=False)),
                ("override_reason", models.CharField(blank=True, max_length=500)),
                ("price_basis", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="line_prices", to="quotations.quotationpricebasis")),
                ("quotation_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="basis_prices", to="quotations.quotationline")),
            ],
            options={"db_table": "quotation_line_price"},
        ),
        migrations.AddField(
            model_name="quotationdispatchrecord",
            name="evidence_file",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="quotation_dispatch_evidence", to="files.businessfile"),
        ),
        migrations.AddField(
            model_name="quotationdispatchrecord",
            name="price_basis",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="dispatch_records", to="quotations.quotationpricebasis"),
        ),
        migrations.CreateModel(
            name="QuotationAcceptance",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("accepted_at", models.DateTimeField()),
                ("source", models.CharField(choices=[("EMAIL", "邮件"), ("PHONE", "电话"), ("MEETING", "会议"), ("OTHER", "其他")], max_length=20)),
                ("note", models.TextField(blank=True)),
                ("customer_contact", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="quotation_acceptances", to="customers.customercontact")),
                ("price_basis", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="acceptances", to="quotations.quotationpricebasis")),
                ("quotation", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="acceptance", to="quotations.quotation")),
                ("quotation_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="acceptances", to="quotations.quotationversion")),
                ("recorded_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="recorded_quotation_acceptances", to="organizations.employee")),
            ],
            options={"db_table": "quotation_acceptance"},
        ),
        migrations.AddConstraint(
            model_name="quotationpricebasis",
            constraint=models.UniqueConstraint(fields=("quotation_version", "label"), name="quote_price_basis_label_uniq"),
        ),
        migrations.AddConstraint(
            model_name="quotationpricebasis",
            constraint=models.UniqueConstraint(condition=models.Q(("is_default", True)), fields=("quotation_version",), name="quote_price_basis_default_uniq"),
        ),
        migrations.AddConstraint(
            model_name="quotationpricebasis",
            constraint=models.UniqueConstraint(fields=("quotation_version", "sort_order"), name="quote_price_basis_sort_uniq"),
        ),
        migrations.AddConstraint(
            model_name="quotationlineprice",
            constraint=models.UniqueConstraint(fields=("quotation_line", "price_basis"), name="quote_line_price_basis_uniq"),
        ),
        migrations.AddConstraint(
            model_name="quotationlineprice",
            constraint=models.CheckConstraint(condition=models.Q(("unit_price__gte", 0)), name="quote_line_basis_price_nonneg"),
        ),
        migrations.AddConstraint(
            model_name="quotationlineprice",
            constraint=models.CheckConstraint(condition=models.Q(is_manual_override=False) | ~models.Q(override_reason=""), name="quote_line_override_reason_required"),
        ),
        migrations.AddConstraint(
            model_name="quotationacceptance",
            constraint=models.CheckConstraint(condition=models.Q(("source__in", ["EMAIL", "PHONE", "MEETING", "OTHER"])), name="quotation_acceptance_source_valid"),
        ),
    ]
