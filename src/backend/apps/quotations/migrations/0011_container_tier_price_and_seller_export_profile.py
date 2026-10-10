from decimal import Decimal

from django.db import migrations, models
from django.db.models import Q


TEMPLATE_CODE = "HAIQU_FIXED_BILINGUAL"
SELLER_COMPANY_NAME = "JINHUA SUPERGROUP LEISURE PRODUCTS CO.,LTD"


def populate_container_prices_and_seller_profile(apps, schema_editor):
    QuotationContainerTier = apps.get_model("quotations", "QuotationContainerTier")
    QuotationTemplate = apps.get_model("quotations", "QuotationTemplate")

    for tier in QuotationContainerTier.objects.select_related("quotation_line").all().iterator():
        tier.unit_price = tier.quotation_line.unit_price or Decimal("0")
        tier.save(update_fields=["unit_price"])

    template = QuotationTemplate.objects.filter(template_code=TEMPLATE_CODE).first()
    if template is not None:
        config = dict(template.template_config or {})
        config.setdefault("seller_company_name", SELLER_COMPANY_NAME)
        config.setdefault("seller_fax", "")
        config.setdefault("seller_skype", "")
        config.setdefault("seller_qq", "")
        template.template_config = config
        template.save(update_fields=["template_config", "updated_at"])


def remove_seller_export_profile(apps, schema_editor):
    QuotationTemplate = apps.get_model("quotations", "QuotationTemplate")
    template = QuotationTemplate.objects.filter(template_code=TEMPLATE_CODE).first()
    if template is not None:
        config = dict(template.template_config or {})
        for key in ("seller_company_name", "seller_fax", "seller_skype", "seller_qq"):
            config.pop(key, None)
        template.template_config = config
        template.save(update_fields=["template_config", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("quotations", "0010_quote_scoped_container_tier"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotationcontainertier",
            name="unit_price",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.RunPython(populate_container_prices_and_seller_profile, remove_seller_export_profile),
        migrations.AlterField(
            model_name="quotationcontainertier",
            name="unit_price",
            field=models.DecimalField(decimal_places=4, max_digits=18),
        ),
        migrations.AddConstraint(
            model_name="quotationcontainertier",
            constraint=models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="quote_container_tier_unit_price_nonneg",
            ),
        ),
    ]
