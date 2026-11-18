from django.db import migrations


PIECE_UNIT_CODE = "BOM_CUT_PIECE"


def ensure_cut_piece_unit(apps, schema_editor):
    ProductionUnit = apps.get_model("reference_data", "ProductionUnit")
    units = ProductionUnit.objects.using(schema_editor.connection.alias)
    existing = units.filter(unit_name="片").first()
    if existing is not None:
        if existing.status != "ACTIVE" or existing.archived_at is not None:
            raise RuntimeError("部位裁片流程需要有效的生产单位“片”；已有记录已停用或归档，请经业务确认处理后重试迁移。")
        return
    if units.filter(unit_code=PIECE_UNIT_CODE).exists():
        raise RuntimeError("裁片单位代码 BOM_CUT_PIECE 已被其他单位占用，请核对单位维护资料后重试迁移。")
    units.create(unit_code=PIECE_UNIT_CODE, unit_name="片", status="ACTIVE",
                 description="部位裁片流程必需单位：裁片按片记账。")


class Migration(migrations.Migration):
    dependencies = [
        ("boms", "0020_bom_component_parts"),
        ("reference_data", "0032_purchase_payable_number_rule"),
    ]
    # 回滚代码不能删除可能已经被库存和外发引用的生产单位。
    operations = [migrations.RunPython(ensure_cut_piece_unit, migrations.RunPython.noop)]
