from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inquiries", "0004_inquirydraftrevision_and_more"),
        ("quotations", "0005_quotationversion_parent_version_and_line_lineage"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotation",
            name="creation_idempotency_key",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddConstraint(
            model_name="quotation",
            constraint=models.UniqueConstraint(
                condition=~Q(("creation_idempotency_key", "")),
                fields=("creation_idempotency_key",),
                name="quotation_create_idempotency_uniq",
            ),
        ),
        migrations.AddField(
            model_name="quotationversion",
            name="customer_requirement_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="quotationline",
            name="source_inquiry_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_lines",
                to="inquiries.inquiryitem",
            ),
        ),
        migrations.RemoveConstraint(model_name="quotationline", name="quotation_line_price_nonneg"),
        migrations.RemoveConstraint(model_name="quotationline", name="quotation_line_total_nonneg"),
        migrations.AlterField(
            model_name="quotationline",
            name="unit_price",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AlterField(
            model_name="quotationline",
            name="line_total",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddConstraint(
            model_name="quotationline",
            constraint=models.CheckConstraint(
                condition=Q(("unit_price__isnull", True), ("unit_price__gte", 0), _connector="OR"),
                name="quotation_line_price_nonneg",
            ),
        ),
        migrations.AddConstraint(
            model_name="quotationline",
            constraint=models.CheckConstraint(
                condition=Q(("line_total__isnull", True), ("line_total__gte", 0), _connector="OR"),
                name="quotation_line_total_nonneg",
            ),
        ),
    ]
