"""事务测试在前一个用例清库后补齐采购夹具使用的权限和业务种子。"""
from django.apps import apps
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Permission

from apps.products.models import ProductInformation, RawMaterialInformation
from apps.reference_data.models import Currency, ProductCategory, ProductItem, ProductionUnit


def ensure_group_test_reference_data():
    if not Permission.objects.filter(content_type__app_label="procurement", codename="view_purchaseorder").exists():
        for label in ("procurement", "inventory", "production_tasks", "access_control"):
            create_permissions(apps.get_app_config(label), verbosity=0)
    Currency.objects.get_or_create(code="CNY", defaults={"numeric_code": "156", "chinese_name": "人民币"})
    unit, _ = ProductionUnit.objects.get_or_create(unit_name="PCS", defaults={"unit_code": "U1-PCS"})
    if not ProductInformation.objects.filter(status="ACTIVE", archived_at__isnull=True).exclude(product_code="").exists():
        category, _ = ProductCategory.objects.get_or_create(item_type="FINISHED", category_name="U1事务测试成品")
        item, _ = ProductItem.objects.get_or_create(item_number="U1-TX-PRODUCT", defaults={"category": category})
        ProductInformation.objects.create(product_number="U1-TX-001", product_code="U1-TX",
            category=category, product_item=item, product_name="U1事务测试产品", specification="60×80",
            unit=unit, scale="REGULAR")
    if not RawMaterialInformation.objects.filter(item_type="MATERIAL", archived_at__isnull=True, unit__unit_name="PCS").exists():
        category, _ = ProductCategory.objects.get_or_create(item_type="MATERIAL", category_name="U1事务测试配件")
        RawMaterialInformation.objects.create(item_type="MATERIAL", material_number="U1-TX-MATERIAL",
            category=category, material_name="U1事务测试材料", specification="M8", unit=unit,
            warehouse_number="U1-TX-WH", warehouse_name="U1事务测试仓")
