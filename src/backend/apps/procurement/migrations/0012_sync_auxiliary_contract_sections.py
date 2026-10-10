from copy import deepcopy
import re

from django.db import migrations
from django.utils import timezone


TEMPLATE_CODES = (
    "PLASTIC_PART",
    "FABRIC",
    "AUXILIARY",
    "FOAM_CUTTING",
    "WEBBING_ACTUAL_WEIGHT",
)

SHARED_SECTION_KEYS = (
    "payment_and_delivery",
    "quality_standards",
    "delivery_handover",
    "special_instructions",
    "dispute_resolution",
    "effectiveness",
)


def _current_version(version_model, template):
    version = version_model.objects.filter(
        template_id=template.id,
        version_number=template.current_version_number,
    ).first()
    if version is not None:
        return version
    return version_model.objects.filter(template_id=template.id).order_by("-version_number", "-id").first()


def _normalized_auxiliary_sections(content):
    sections = {key: deepcopy(content.get(key)) for key in SHARED_SECTION_KEYS}

    payment_text = str(sections.get("payment_and_delivery") or "")
    payment_text = re.sub(
        r"\d{4}年\d{1,2}月\d{1,2}日(?=前)",
        "{{采购交期}}",
        payment_text,
        count=1,
    )
    sections["payment_and_delivery"] = payment_text

    dispute_text = str(sections.get("dispute_resolution") or "")
    sections["dispute_resolution"] = dispute_text.replace("不能屡约", "不能履约")

    special_text = str(sections.get("special_instructions") or "")
    sections["special_instructions"] = (
        special_text
        .replace("给与或者给与", "给予或者给予")
        .replace("向乙方赔偿损失", "向甲方赔偿损失")
    )
    return sections


def sync_auxiliary_contract_sections(apps, schema_editor):
    template_model = apps.get_model("procurement", "PurchaseContractTemplate")
    version_model = apps.get_model("procurement", "PurchaseContractTemplateVersion")

    source_template = template_model.objects.filter(
        template_code="AUXILIARY",
        archived_at__isnull=True,
    ).first()
    if source_template is None:
        return

    source_version = _current_version(version_model, source_template)
    if source_version is None or not isinstance(source_version.content_config, dict):
        return

    shared_sections = _normalized_auxiliary_sections(source_version.content_config)
    templates = template_model.objects.filter(
        template_code__in=TEMPLATE_CODES,
        archived_at__isnull=True,
    ).order_by("template_code", "id")

    for template in templates:
        current_version = _current_version(version_model, template)
        if current_version is None:
            continue

        content = deepcopy(current_version.content_config) if isinstance(current_version.content_config, dict) else {}
        content.pop("terms", None)
        content.update(deepcopy(shared_sections))

        latest_number = (
            version_model.objects.filter(template_id=template.id)
            .order_by("-version_number")
            .values_list("version_number", flat=True)
            .first()
            or 0
        )
        new_version_number = max(template.current_version_number, latest_number) + 1
        version_model.objects.create(
            template_id=template.id,
            version_number=new_version_number,
            version_name="辅料条款同步版",
            content_config=content,
            change_summary="同步辅料采购合同正文，采购交期改为采购明细变量，并修正已知错字。",
            created_by_employee_id=current_version.created_by_employee_id,
        )
        template.current_version_number = new_version_number
        template.updated_at = timezone.now()
        template.save(update_fields=["current_version_number", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("procurement", "0011_purchasecontracttemplateversion_version_name")]

    operations = [
        migrations.RunPython(sync_auxiliary_contract_sections, migrations.RunPython.noop),
    ]
