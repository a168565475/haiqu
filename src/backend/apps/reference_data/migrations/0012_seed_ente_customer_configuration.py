import uuid
from copy import deepcopy

from django.db import migrations
from django.utils import timezone


NAMESPACE = uuid.UUID("d8f32273-9f99-482f-9bd4-9e4b4a2464ed")


DICTIONARY_TYPES = (
    ("CUSTOMER_INDUSTRY", "所属行业", 120),
    ("CUSTOMER_INTERESTED_PRODUCT", "感兴趣产品", 130),
    ("CUSTOMER_CREDIT_GRADE", "信用等级", 140),
)

DICTIONARY_ITEMS = (
    ("CUSTOMER_SOURCE", "ALIBABA_CHINA", "阿里诚信通", 10),
    ("CUSTOMER_SOURCE", "ALIBABA_INTERNATIONAL", "阿里国际", 20),
    ("CUSTOMER_SOURCE", "MADE_IN_CHINA", "中国制造网", 30),
    ("CUSTOMER_SOURCE", "EMAIL", "企业邮箱", 40),
    ("CUSTOMER_SOURCE", "CANTON_FAIR", "广交会", 50),
    ("CUSTOMER_SOURCE", "COLOGNE_FAIR", "德国科隆展", 60),
    ("CUSTOMER_SOURCE", "LAS_VEGAS_FAIR", "拉斯维加斯展", 70),
    ("CUSTOMER_SOURCE", "BRAZIL_FAIR", "巴西展", 80),
    ("CUSTOMER_SOURCE", "OTHER", "其他", 90),
    ("CUSTOMER_SOURCE", "HONG_KONG_FAIR", "香港展", 100),
    ("CUSTOMER_TYPE", "POTENTIAL", "潜在客户", 10),
    ("CUSTOMER_TYPE", "FORMAL", "正式客户", 20),
    ("CUSTOMER_TYPE", "FORWARDER", "货代", 30),
    ("CUSTOMER_INDUSTRY", "FOREIGN_IMPORT_EXPORT", "国外进出口公司", 10),
    ("CUSTOMER_INDUSTRY", "HONG_KONG_TAIWAN_FOREIGN_TRADE", "港台外贸公司", 20),
    ("CUSTOMER_INDUSTRY", "DOMESTIC_FOREIGN_TRADE", "国内外贸公司", 30),
    ("CUSTOMER_INDUSTRY", "FOREIGN_PROMOTIONAL_GIFTS", "国外促销礼品公司", 40),
    ("CUSTOMER_INDUSTRY", "FOREIGN_CHAIN_SUPERMARKET", "国外大型连锁超市", 50),
    ("CUSTOMER_INDUSTRY", "FOREIGN_DAILY_CHAIN", "国外连锁日用购物", 60),
    ("CUSTOMER_INDUSTRY", "FOREIGN_END_CUSTOMER", "国外最终客户", 70),
    ("CUSTOMER_INDUSTRY", "FOREIGN_WHOLESALER", "国外批发商", 80),
    ("CUSTOMER_INDUSTRY", "FOREIGN_RETAILER", "国外零售商", 90),
    ("CUSTOMER_INDUSTRY", "DOMESTIC_GIFTS", "国内礼品公司", 100),
    ("CUSTOMER_INDUSTRY", "DOMESTIC_END_CUSTOMER", "国内最终客户", 110),
    ("CUSTOMER_INDUSTRY", "DOMESTIC_RETAILER", "国内零售商", 120),
    ("CUSTOMER_INDUSTRY", "DOMESTIC_WHOLESALER", "国内批发公司", 130),
    ("CUSTOMER_INDUSTRY", "OTHER", "其他", 140),
    ("CUSTOMER_INTERESTED_PRODUCT", "FOLDING_FURNITURE", "折叠床/桌/椅", 10),
    ("CUSTOMER_INTERESTED_PRODUCT", "CART_BASKET_BAG", "购物车/篮/袋/包", 20),
    ("CUSTOMER_INTERESTED_PRODUCT", "CANOPY_AWNING_UMBRELLA", "车棚/凉棚/遮阳伞", 30),
    ("CUSTOMER_INTERESTED_PRODUCT", "TENT_SLEEPING_BAG", "帐篷/睡袋", 40),
    ("CUSTOMER_INTERESTED_PRODUCT", "RATTAN_FURNITURE", "编藤套装桌椅", 50),
    ("CUSTOMER_INTERESTED_PRODUCT", "HANGING_CHAIR", "吊篮", 60),
    ("CUSTOMER_INTERESTED_PRODUCT", "SWING", "秋千", 70),
    ("CUSTOMER_INTERESTED_PRODUCT", "HARDWARE", "杯子，酒具，柠檬夹，饭盒等五金类", 80),
    ("CUSTOMER_INTERESTED_PRODUCT", "FITNESS", "健身器材，哑铃，跑步机类", 90),
    ("CUSTOMER_INTERESTED_PRODUCT", "PANDEMIC_SUPPLIES", "防疫物资，口罩，试剂类", 100),
    ("CUSTOMER_INTERESTED_PRODUCT", "VEHICLE", "车类", 110),
    ("CUSTOMER_INTERESTED_PRODUCT", "REFLECTIVE_VEST", "反光背心", 120),
    ("CUSTOMER_INTERESTED_PRODUCT", "OTHER", "其他", 130),
    ("CUSTOMER_CREDIT_GRADE", "A", "A级", 10),
    ("CUSTOMER_CREDIT_GRADE", "B", "B级", 20),
    ("CUSTOMER_CREDIT_GRADE", "C", "C级", 30),
    ("CUSTOMER_CREDIT_GRADE", "D", "D级", 40),
    ("CUSTOMER_CREDIT_GRADE", "E", "E级", 50),
)


def fixed_id(prefix, value):
    return uuid.uuid5(NAMESPACE, f"{prefix}:{value}")


def publish_snapshot(apps):
    ConfigRelease = apps.get_model("reference_data", "ConfigRelease")
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    latest = ConfigRelease.objects.filter(status="PUBLISHED").order_by("-version").first()
    snapshot = deepcopy(latest.snapshot if latest else {})
    options = snapshot.setdefault("dictionary_options", {})
    affected_categories = {row[0] for row in DICTIONARY_ITEMS}
    for category_code in affected_categories:
        rows = ReferenceDictionary.objects.filter(
            category_code=category_code,
            status="ACTIVE",
            archived_at__isnull=True,
        ).order_by("sort_order", "item_code")
        options[category_code] = [
            {
                "id": str(row.pk),
                "code": row.item_code,
                "label": row.display_name,
                "english_label": row.english_name,
                "status": row.status,
                "sort_order": row.sort_order,
                "color": row.color,
                "extra": {**row.extra_data, "description": row.description},
            }
            for row in rows
        ]
    latest_version = ConfigRelease.objects.order_by("-version").values_list("version", flat=True).first() or 0
    ConfigRelease.objects.create(
        version=latest_version + 1,
        status="PUBLISHED",
        notes="同步恩特 ERP 客户来源、类型、行业、感兴趣产品与信用等级配置。",
        snapshot=snapshot,
        published_at=timezone.now(),
    )


def seed_configuration(apps, schema_editor):
    DictionaryType = apps.get_model("reference_data", "DictionaryType")
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    for code, name, sort_order in DICTIONARY_TYPES:
        dictionary_type, _created = DictionaryType.objects.get_or_create(
            code=code,
            defaults={
                "id": fixed_id("TYPE", code),
                "chinese_name": name,
                "english_name": "",
                "group_code": "CUSTOMER",
                "sort_order": sort_order,
                "status": "ACTIVE",
                "description": "恩特 ERP 客户资料配置",
            },
        )
        DictionaryType.objects.filter(pk=dictionary_type.pk).update(
            chinese_name=name,
            english_name="",
            group_code="CUSTOMER",
            sort_order=sort_order,
            status="ACTIVE",
            description="恩特 ERP 客户资料配置",
        )
    for category, item_code, label, sort_order in DICTIONARY_ITEMS:
        dictionary_type = DictionaryType.objects.get(code=category)
        item, _created = ReferenceDictionary.objects.get_or_create(
            category_code=category,
            item_code=item_code,
            defaults={
                "id": fixed_id("ITEM", f"{category}:{item_code}"),
                "dictionary_type": dictionary_type,
                "display_name": label,
                "english_name": "",
                "sort_order": sort_order,
                "status": "ACTIVE",
                "description": "恩特 ERP 客户资料配置",
                "extra_data": {},
            },
        )
        ReferenceDictionary.objects.filter(pk=item.pk).update(
            dictionary_type=dictionary_type,
            display_name=label,
            english_name="",
            sort_order=sort_order,
            status="ACTIVE",
            description="恩特 ERP 客户资料配置",
            extra_data={},
        )
    ReferenceDictionary.objects.filter(category_code="CUSTOMER_SOURCE").exclude(
        item_code__in=[row[1] for row in DICTIONARY_ITEMS if row[0] == "CUSTOMER_SOURCE"]
    ).update(status="INACTIVE")
    ReferenceDictionary.objects.filter(category_code="CUSTOMER_TYPE").exclude(
        item_code__in=[row[1] for row in DICTIONARY_ITEMS if row[0] == "CUSTOMER_TYPE"]
    ).update(status="INACTIVE")
    publish_snapshot(apps)


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0011_publish_inquiry_customer_grade")]

    operations = [migrations.RunPython(seed_configuration, migrations.RunPython.noop)]
