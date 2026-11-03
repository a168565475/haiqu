"""事务测试每次显式补齐业务种子，让标准 flush/post_migrate 恢复权限。"""
from apps.products.models import ProductInformation, RawMaterialInformation
from apps.reference_data.models import Currency, ProductCategory, ProductItem, ProductionUnit


def ensure_group_test_reference_data():
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
