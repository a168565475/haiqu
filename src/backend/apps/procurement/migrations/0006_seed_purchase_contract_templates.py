import uuid

from django.db import migrations


BUYER = {
    "name": "浙江嗨趣休闲用品有限公司",
    "address": "",
    "contact": "",
    "phone": "",
}

COMMON_TERMS = [
    "乙方供应的产品应符合双方确认的规格、样品及质量要求，不得侵犯第三方知识产权。",
    "乙方应按约定交期送达甲方指定地点；因乙方原因延期或质量不合格造成的损失，由乙方承担。",
    "到货后由甲方验收；不合格品由乙方负责退换并承担相关费用。",
    "合同履行发生争议时，双方先协商解决；协商不成，向甲方所在地有管辖权的人民法院起诉。",
]


TEMPLATES = [
    (
        "PLASTIC_PART",
        "塑料件采购合同",
        ["PLASTIC_PART"],
        {
            "title": "塑料件采购合同",
            "buyer": BUYER,
            "settlement_mode": "NORMAL",
            "tax_rate": "13",
            "freight_bearer": "乙方",
            "show_image": True,
            "terms": COMMON_TERMS,
            "legal_review_notice": "合同条款正式启用前仍需人工审核。",
        },
    ),
    (
        "FABRIC",
        "布面采购合同",
        ["FABRIC"],
        {
            "title": "布面采购合同",
            "buyer": BUYER,
            "settlement_mode": "NORMAL",
            "tax_rate": "13",
            "freight_bearer": "乙方",
            "show_image": True,
            "terms": COMMON_TERMS,
            "legal_review_notice": "合同条款正式启用前仍需人工审核。",
        },
    ),
    (
        "AUXILIARY",
        "辅料采购合同",
        ["AUXILIARY"],
        {
            "title": "辅料采购合同",
            "buyer": BUYER,
            "settlement_mode": "NORMAL",
            "tax_rate": "13",
            "freight_bearer": "乙方",
            "show_image": True,
            "terms": COMMON_TERMS,
            "legal_review_notice": "合同条款正式启用前仍需人工审核。",
        },
    ),
    (
        "FOAM_CUTTING",
        "喷胶棉/裁片采购合同",
        ["AUXILIARY"],
        {
            "title": "喷胶棉/裁片采购合同",
            "buyer": BUYER,
            "settlement_mode": "NORMAL",
            "tax_rate": "13",
            "freight_bearer": "甲方",
            "show_image": True,
            "terms": COMMON_TERMS,
            "legal_review_notice": "合同条款正式启用前仍需人工审核。",
        },
    ),
    (
        "WEBBING_ACTUAL_WEIGHT",
        "织带按实结算采购合同",
        ["AUXILIARY"],
        {
            "title": "织带采购合同",
            "buyer": BUYER,
            "settlement_mode": "ACTUAL_WEIGHT",
            "tax_rate": "13",
            "freight_bearer": "甲方",
            "show_image": True,
            "terms": COMMON_TERMS,
            "legal_review_notice": "合同条款正式启用前仍需人工审核。",
        },
    ),
]


def seed_templates(apps, schema_editor):
    template_model = apps.get_model("procurement", "PurchaseContractTemplate")
    version_model = apps.get_model("procurement", "PurchaseContractTemplateVersion")
    for index, (code, name, categories, config) in enumerate(TEMPLATES, start=1):
        template_id = uuid.UUID(f"7c950000-0000-4000-8000-{index:012d}")
        version_id = uuid.UUID(f"7c960000-0000-4000-8000-{index:012d}")
        template, _ = template_model.objects.update_or_create(
            template_code=code,
            defaults={
                "id": template_id,
                "template_name": name,
                "supplier_categories": categories,
                "status": "ACTIVE",
                "current_version_number": 1,
            },
        )
        version_model.objects.update_or_create(
            template=template,
            version_number=1,
            defaults={
                "id": version_id,
                "content_config": config,
                "change_summary": "根据真实采购合同建立的首版模板，正式使用前请人工审核合同条款。",
            },
        )


def remove_templates(apps, schema_editor):
    template_model = apps.get_model("procurement", "PurchaseContractTemplate")
    template_model.objects.filter(template_code__in=[item[0] for item in TEMPLATES]).delete()


class Migration(migrations.Migration):
    dependencies = [("procurement", "0005_alter_purchaseorder_status_purchasecontracttemplate_and_more")]

    operations = [migrations.RunPython(seed_templates, remove_templates)]
