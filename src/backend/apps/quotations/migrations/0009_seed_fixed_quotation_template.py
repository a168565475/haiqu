from django.db import migrations


TEMPLATE_CODE = "HAIQU_FIXED_BILINGUAL"


def create_fixed_template(apps, schema_editor):
    QuotationTemplate = apps.get_model("quotations", "QuotationTemplate")
    QuotationVersion = apps.get_model("quotations", "QuotationVersion")

    template, _ = QuotationTemplate.objects.update_or_create(
        template_code=TEMPLATE_CODE,
        defaults={
            "template_name": "haiqu 中英文固定报价模板",
            "template_version": 1,
            "requires_approval": False,
            "template_config": {
                "brand_name": "haiqu",
                "document_title": "QUOTATION / 报价单",
                "locale": "zh-CN/en",
                "output_format": "PDF",
                "sender_email": "quotation@haiqu.example",
                "email_subject": "Quotation {quotation_number} from haiqu",
                "email_body": "Dear Customer,\n\nPlease find our quotation attached.\n\nBest regards,\nhaiqu team",
                "sender_email_is_virtual": True,
            },
        },
    )
    QuotationVersion.objects.filter(
        quotation_template__isnull=True,
        status="DRAFT",
    ).update(quotation_template=template)


def remove_fixed_template(apps, schema_editor):
    QuotationTemplate = apps.get_model("quotations", "QuotationTemplate")
    QuotationVersion = apps.get_model("quotations", "QuotationVersion")
    template = QuotationTemplate.objects.filter(template_code=TEMPLATE_CODE).first()
    if template is not None:
        QuotationVersion.objects.filter(quotation_template=template).update(quotation_template=None)
        template.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("quotations", "0008_sales_quotation_closure"),
    ]

    operations = [
        migrations.RunPython(create_fixed_template, remove_fixed_template),
    ]
