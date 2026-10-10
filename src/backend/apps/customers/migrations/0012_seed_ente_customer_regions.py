import uuid

from django.db import migrations


NAMESPACE = uuid.UUID("c69a11db-7f48-47ef-9bb5-2a02ca803c11")

PRIMARY_REGIONS = (
    ("1", "0001", "亚洲", 10),
    ("2", "0002", "非洲", 20),
    ("3", "0003", "欧洲", 30),
    ("4", "0004", "拉丁美洲", 40),
    ("5", "0005", "北美洲", 50),
    ("6", "0006", "大洋洲", 60),
    ("7", "0007", "国内", 70),
)

DOMESTIC_REGIONS = (
    ("CN110000", "00070001", "北京市"), ("CN120000", "00070002", "天津市"),
    ("CN130000", "00070003", "河北省"), ("CN140000", "00070004", "山西省"),
    ("CN150000", "00070005", "内蒙古自治区"), ("CN210000", "00070006", "辽宁省"),
    ("CN220000", "00070007", "吉林省"), ("CN230000", "00070008", "黑龙江省"),
    ("CN310000", "00070009", "上海市"), ("CN320000", "00070010", "江苏省"),
    ("CN330000", "00070011", "浙江省"), ("CN340000", "00070012", "安徽省"),
    ("CN350000", "00070013", "福建省"), ("CN360000", "00070014", "江西省"),
    ("CN370000", "00070015", "山东省"), ("CN410000", "00070016", "河南省"),
    ("CN420000", "00070017", "湖北省"), ("CN430000", "00070018", "湖南省"),
    ("CN440000", "00070019", "广东省"), ("CN450000", "00070020", "广西壮族自治区"),
    ("CN460000", "00070021", "海南省"), ("CN500000", "00070022", "重庆市"),
    ("CN510000", "00070023", "四川省"), ("CN520000", "00070024", "贵州省"),
    ("CN530000", "00070025", "云南省"), ("CN540000", "00070026", "西藏自治区"),
    ("CN610000", "00070027", "陕西省"), ("CN620000", "00070028", "甘肃省"),
    ("CN630000", "00070029", "青海省"), ("CN640000", "00070030", "宁夏回族自治区"),
    ("CN650000", "00070031", "新疆维吾尔自治区"), ("CN710000", "00070032", "台湾省"),
    ("CN810000", "00070033", "香港特别行政区"), ("CN820000", "00070034", "澳门特别行政区"),
)

# 当前导入客户使用到的旧树编号。其余国家使用稳定的扩展编号，选择编号始终是国家代码。
TREE_CODE_OVERRIDES = {
    "AE": "00010037", "AL": "00030035", "AR": "00040002", "AU": "00060001",
    "BE": "00030001", "CA": "00050001", "CH": "00030031", "CN": "00010040",
    "CR": "00040010", "DE": "00030004", "FR": "00030005", "GB": "00030003",
    "HK": "00010010", "HR": "00030046", "IN": "00010011", "IR": "00010013",
    "IT": "00030007", "JP": "00010016", "MX": "00040021", "NL": "00030009",
    "OM": "00010026", "PA": "00040024", "PE": "00040026", "TH": "00010035",
    "TR": "00010036", "US": "00050002", "ZA": "00020038",
}


def item_id(value):
    return uuid.uuid5(NAMESPACE, value)


def region_group(country):
    if country.code in {"CA", "US", "BM"}:
        return "0005"
    region_name = (country.extra_data or {}).get("region_name", "")
    return {
        "Asia": "0001",
        "Africa": "0002",
        "Europe": "0003",
        "Americas": "0004",
        "Oceania": "0006",
    }.get(region_name)


def seed_regions(apps, schema_editor):
    CustomerRegion = apps.get_model("customers", "CustomerRegion")
    Country = apps.get_model("reference_data", "Country")
    primary_by_tree = {}
    for selector_code, tree_code, name, sort_order in PRIMARY_REGIONS:
        region, _created = CustomerRegion.objects.get_or_create(
            legacy_selector_code=selector_code,
            defaults={
                "id": item_id(f"PRIMARY:{tree_code}"),
                "legacy_tree_code": tree_code,
                "region_name": name,
                "level": 1,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
        CustomerRegion.objects.filter(pk=region.pk).update(
            legacy_tree_code=tree_code,
            region_name=name,
            level=1,
            parent=None,
            country=None,
            sort_order=sort_order,
            is_active=True,
        )
        primary_by_tree[tree_code] = region

    for country in Country.objects.filter(status="ACTIVE", archived_at__isnull=True).order_by("sort_order", "code"):
        if country.code in {"KP", "KR"}:
            continue
        parent_code = region_group(country)
        if not parent_code:
            continue
        tree_code = TREE_CODE_OVERRIDES.get(country.code, f"{parent_code}{country.sort_order:04d}")
        region, _created = CustomerRegion.objects.get_or_create(
            legacy_selector_code=country.code,
            defaults={
                "id": item_id(f"COUNTRY:{country.code}"),
                "legacy_tree_code": tree_code,
                "region_name": country.chinese_name,
                "level": 2,
                "parent": primary_by_tree[parent_code],
                "country": country,
                "sort_order": country.sort_order,
                "is_active": True,
            },
        )
        CustomerRegion.objects.filter(pk=region.pk).update(
            legacy_tree_code=tree_code,
            region_name=country.chinese_name,
            level=2,
            parent=primary_by_tree[parent_code],
            country=country,
            sort_order=country.sort_order,
            is_active=True,
        )

    china = Country.objects.get(code="CN")
    domestic = primary_by_tree["0007"]
    for sort_order, (selector_code, tree_code, name) in enumerate(DOMESTIC_REGIONS, start=1):
        region, _created = CustomerRegion.objects.get_or_create(
            legacy_selector_code=selector_code,
            defaults={
                "id": item_id(f"DOMESTIC:{selector_code}"),
                "legacy_tree_code": tree_code,
                "region_name": name,
                "level": 2,
                "parent": domestic,
                "country": china,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
        CustomerRegion.objects.filter(pk=region.pk).update(
            legacy_tree_code=tree_code,
            region_name=name,
            level=2,
            parent=domestic,
            country=china,
            sort_order=sort_order,
            is_active=True,
        )

    # 恩特旧树的历史例外：编号保留，国家字段使用标准 ISO 代码；南斯拉夫没有现代国家映射。
    exceptions = (
        ("KR", "00010009", "朝鲜", "KP", "0001", 9),
        ("KP", "00010032", "韩国", "KR", "0001", 32),
        ("RUS", "00030049", "俄罗斯", "RU", "0003", 49),
        ("YU", "00030044", "南斯拉夫", None, "0003", 44),
    )
    for selector_code, tree_code, name, country_code, parent_code, sort_order in exceptions:
        country = Country.objects.filter(code=country_code).first() if country_code else None
        region, _created = CustomerRegion.objects.get_or_create(
            legacy_selector_code=selector_code,
            defaults={
                "id": item_id(f"EXCEPTION:{selector_code}"),
                "legacy_tree_code": tree_code,
                "region_name": name,
                "level": 2,
                "parent": primary_by_tree[parent_code],
                "country": country,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
        CustomerRegion.objects.filter(pk=region.pk).update(
            legacy_tree_code=tree_code,
            region_name=name,
            level=2,
            parent=primary_by_tree[parent_code],
            country=country,
            sort_order=sort_order,
            is_active=True,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0011_customer_profile_configuration"),
        ("reference_data", "0012_seed_ente_customer_configuration"),
    ]

    operations = [migrations.RunPython(seed_regions, migrations.RunPython.noop)]
