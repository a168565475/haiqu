from django.db import migrations


UNIT_BY_PRODUCT_NAME = {
    "布料": "米",
    "铆钉": "个",
    "尖角半圆皮": "个",
    "调节圈": "个",
    "海绵套": "个",
    "魔术贴（毛）": "米",
    "魔术贴（齿)": "米",
    "扭柱": "个",
    "塑料管套": "个",
    "管套": "个",
    "支撑缺卡件": "个",
    "对孔管套": "个",
    "扶手": "套",
    "左扶手": "套",
    "全通": "个",
    "后半通": "个",
    "前半通": "个",
    "凸塞": "个",
    "大全通": "个",
    "半通加厚": "个",
    "半通": "个",
    "平衡块": "个",
    "双面夹": "个",
    "钢筋": "根",
    "五档齿条": "个",
    "弹簧（左右）": "对",
    "平塞": "个",
    "M5螺帽": "个",
    "半圆机": "个",
    "十字扁平头螺丝": "个",
    "大扁头自攻螺丝": "个",
    "铁垫片": "个",
    "带垫自攻螺丝": "个",
    "大带垫自攻螺丝": "个",
    "组合上杯圈": "个",
    "组合下杯圈": "个",
}


def fill_units(apps, schema_editor):
    AccessoryProductName = apps.get_model("reference_data", "AccessoryProductName")
    db_alias = schema_editor.connection.alias
    for product_name, unit_name in UNIT_BY_PRODUCT_NAME.items():
        AccessoryProductName.objects.using(db_alias).filter(
            product_name=product_name,
            unit_name="",
        ).update(
            unit_name=unit_name,
            description="补充品名单位已按业务用途维护。",
        )


def clear_units(apps, schema_editor):
    AccessoryProductName = apps.get_model("reference_data", "AccessoryProductName")
    db_alias = schema_editor.connection.alias
    AccessoryProductName.objects.using(db_alias).filter(
        product_name__in=UNIT_BY_PRODUCT_NAME,
        description="补充品名单位已按业务用途维护。",
    ).update(
        unit_name="",
        description="由辅料规格/颜色表关联补充；单位待维护。",
    )


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0027_fabric_accessory_inventory_raw_material")]

    operations = [migrations.RunPython(fill_units, clear_units)]
