from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.db import migrations, models
from django.db.models import F, Func, Q, Value
from decimal import Decimal
import django.db.models.deletion
import uuid


def backfill_scope_craft(apps, schema_editor):
    WageScheme = apps.get_model("workshop_reporting", "WageScheme")
    WageSchemeCraft = apps.get_model("workshop_reporting", "WageSchemeCraft")
    alias = schema_editor.connection.alias
    for scheme in WageScheme.objects.using(alias).all().iterator(chunk_size=200):
        craft_ids = list(
            WageSchemeCraft.objects.using(alias)
            .filter(scheme_id=scheme.pk)
            .values_list("craft_id", flat=True)[:2]
        )
        if len(craft_ids) != 1:
            raise RuntimeError(f"工价方案 {scheme.pk} 未关联唯一工艺，无法建立计划进度范围。")
        WageScheme.objects.using(alias).filter(pk=scheme.pk).update(scope_craft_id=craft_ids[0])


def backfill_required_quantities(apps, schema_editor):
    Bom = apps.get_model("boms", "Bom")
    BomLine = apps.get_model("boms", "BomLine")
    WageSchemeLine = apps.get_model("workshop_reporting", "WageSchemeLine")
    WorkItem = apps.get_model("workshop_reporting", "WorkItem")
    alias = schema_editor.connection.alias
    legacy_metal_material_overrides = {
        # 旧方案创建时尚未保存材质；以下映射由业务方逐条确认。
        ("GJ-202609-000005", "扶手支撑左-16*0.7*425", "管口冲员"): "铁",
        ("GJ-202609-000005", "扶手支撑左-16*0.7*425", "缩管一次"): "铁-中光",
    }
    lines = WageSchemeLine.objects.using(alias).filter(
        required_quantity_snapshot__isnull=True,
    ).select_related(
        "scheme__schedule_product", "scheme__product_line",
        "scheme__scope_craft__workshop", "work_item",
    )
    for line in lines.iterator(chunk_size=200):
        scheme = line.scheme
        craft = scheme.scope_craft
        order_quantity = Decimal(
            scheme.schedule_product.source_quantity_snapshot
            if scheme.schedule_product_id else scheme.product_line.quantity
        )
        plan_category = "METAL" if craft.workshop.name == "金工车间" else craft.plan_category
        counting_mode = "ORDER"
        required_quantity = order_quantity
        bom_line = None

        if plan_category in {"METAL", "CUTTING", "SEWING"}:
            # 旧车缝明细没有记录按套/按片，不能在迁移时猜测。
            if plan_category == "SEWING":
                continue
            bom = Bom.objects.using(alias).filter(
                product_line_id=scheme.product_line_id,
                status="VERIFIED",
                archived_at__isnull=True,
            ).order_by("-version_number", "-updated_at", "-id").first()
            if not bom:
                continue
            section_type = "PROFILE" if plan_category == "METAL" else "FABRIC"
            material_override = legacy_metal_material_overrides.get((
                scheme.scheme_number,
                line.display_name_snapshot,
                line.operation_name_snapshot,
            ))
            candidates = []
            for candidate in BomLine.objects.using(alias).filter(
                section__bom_id=bom.pk,
                section__section_type=section_type,
            ).select_related("section").order_by("section__line_number", "line_number", "id"):
                if plan_category == "CUTTING" and candidate.section.title != "裁剪明细":
                    continue
                name = (candidate.part_name or "").strip()
                material = (candidate.material or "").strip()
                specification = (candidate.specification or "").strip()
                if material_override and material != material_override:
                    continue
                legacy_label = f"{name}-{specification}" if specification else name
                label_parts = [name]
                if plan_category == "METAL" and material:
                    label_parts.append(material)
                if specification:
                    label_parts.append(specification)
                label = "-".join(label_parts)
                if line.display_name_snapshot in {label, legacy_label}:
                    candidates.append(candidate)
            if len(candidates) != 1:
                continue
            bom_line = candidates[0]
            selected_name = (bom_line.part_name or "").strip()
            selected_material = (bom_line.material or "").strip()
            selected_specification = (bom_line.specification or "").strip()
            selected_label_parts = [selected_name]
            if plan_category == "METAL" and selected_material:
                selected_label_parts.append(selected_material)
            if selected_specification:
                selected_label_parts.append(selected_specification)
            selected_label = "-".join(selected_label_parts)
            if plan_category == "METAL":
                if not bom_line.pieces_per_product:
                    continue
                counting_mode = "PIECE"
                required_quantity *= Decimal(bom_line.pieces_per_product)
            else:
                if not bom_line.cutting_sets_per_product or not bom_line.cutting_pieces_per_set:
                    continue
                counting_mode = "SET"
                required_quantity *= Decimal(bom_line.cutting_sets_per_product)

        update_fields = {
            "counting_mode": counting_mode,
            "order_quantity_snapshot": int(order_quantity),
            "required_quantity_snapshot": required_quantity.quantize(Decimal("0.0001")),
        }
        if bom_line:
            update_fields.update({
                "display_name_snapshot": selected_label,
                "bom_component_identity_snapshot": bom_line.component_identity,
                "bom_sets_per_product_snapshot": bom_line.cutting_sets_per_product,
                "bom_pieces_per_set_snapshot": bom_line.cutting_pieces_per_set,
            })
            WorkItem.objects.using(alias).filter(
                pk=line.work_item_id, bom_component_identity__isnull=True,
            ).update(
                bom_component_identity=bom_line.component_identity,
                counting_mode=counting_mode,
                display_name=selected_label,
            )
        else:
            WorkItem.objects.using(alias).filter(pk=line.work_item_id).update(
                counting_mode=counting_mode,
            )
        WageSchemeLine.objects.using(alias).filter(pk=line.pk).update(**update_fields)

    unresolved = list(
        WageSchemeLine.objects.using(alias).filter(
            scheme__status="APPROVED",
            status="ACTIVE",
            required_quantity_snapshot__isnull=True,
        ).values_list("scheme__scheme_number", "display_name_snapshot", "operation_name_snapshot")[:20]
    )
    if unresolved:
        details = "；".join(f"{scheme} / {name} / {operation}" for scheme, name, operation in unresolved)
        raise RuntimeError(f"已有批准工价无法自动确定需完成次数，请先处理：{details}")


class Migration(migrations.Migration):
    dependencies = [
        ("boms", "0009_cutting_usage_fields"),
        ("production_scheduling", "0005_backfill_scheduled_tasks_in_production"),
        ("workshop_config", "0009_remove_operation_required_quantity_per_product"),
        ("workshop_reporting", "0012_workreportline_actual_usage_snapshot"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="wagescheme",
            name="wage_scheme_scope_root_unique",
        ),
        migrations.RemoveConstraint(
            model_name="wagescheme",
            name="wage_scheme_approved_scope_no_overlap",
        ),
        migrations.AddField(
            model_name="wagescheme",
            name="scope_craft",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="scoped_wage_schemes",
                to="workshop_config.craft",
            ),
        ),
        migrations.RunPython(backfill_scope_craft, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="wagescheme",
            name="scope_craft",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="scoped_wage_schemes",
                to="workshop_config.craft",
            ),
        ),
        migrations.AddConstraint(
            model_name="wagescheme",
            constraint=models.UniqueConstraint(
                fields=("product_line", "workshop", "scope_craft"),
                condition=Q(parent_scheme__isnull=True),
                name="wage_scheme_scope_root_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="wagescheme",
            constraint=ExclusionConstraint(
                name="wage_scheme_approved_scope_no_overlap",
                expressions=[
                    ("product_line", RangeOperators.EQUAL),
                    ("workshop", RangeOperators.EQUAL),
                    ("scope_craft", RangeOperators.EQUAL),
                    (
                        Func(
                            F("effective_from"), F("effective_to"), Value("[]"),
                            function="DATERANGE", output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(status="APPROVED"),
            ),
        ),
        migrations.AddField(
            model_name="workitem",
            name="bom_component_identity",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workitem",
            name="counting_mode",
            field=models.CharField(
                choices=[("ORDER", "按订单量"), ("SET", "按套"), ("PIECE", "按片")],
                default="ORDER",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="wageschemeline",
            name="bom_component_identity_snapshot",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="wageschemeline",
            name="counting_mode",
            field=models.CharField(
                choices=[("ORDER", "按订单量"), ("SET", "按套"), ("PIECE", "按片")],
                default="ORDER",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="wageschemeline",
            name="order_quantity_snapshot",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="wageschemeline",
            name="bom_sets_per_product_snapshot",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="wageschemeline",
            name="bom_pieces_per_set_snapshot",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="wageschemeline",
            name="required_quantity_snapshot",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True),
        ),
        migrations.RunPython(backfill_required_quantities, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="workreportline",
            name="actual_usage_snapshot",
        ),
        migrations.RemoveField(
            model_name="workreportline",
            name="actual_usage_unit_snapshot",
        ),
        migrations.AddField(
            model_name="workreportline",
            name="required_quantity_snapshot",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True),
        ),
        migrations.AddField(
            model_name="workreport",
            name="completed_plan",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="WorkshopPlanExecution",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(
                    choices=[("IN_PROGRESS", "进行中"), ("COMPLETED", "已完成")],
                    default="IN_PROGRESS",
                    max_length=20,
                )),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("completed_by_employee", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="completed_workshop_plans", to="organizations.employee",
                )),
                ("craft", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="plan_executions", to="workshop_config.craft",
                )),
                ("schedule_product", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="workshop_plan_executions",
                    to="production_scheduling.productionscheduleproduct",
                )),
            ],
            options={
                "db_table": "workshop_plan_execution",
                "ordering": ["schedule_product", "craft"],
            },
        ),
        migrations.AddConstraint(
            model_name="workshopplanexecution",
            constraint=models.UniqueConstraint(
                fields=("schedule_product", "craft"), name="workshop_plan_execution_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="workshopplanexecution",
            constraint=models.CheckConstraint(
                condition=Q(status__in=("IN_PROGRESS", "COMPLETED")),
                name="workshop_plan_execution_status_valid",
            ),
        ),
        migrations.AddIndex(
            model_name="workshopplanexecution",
            index=models.Index(
                fields=["schedule_product", "status"], name="workshop_plan_exec_status_idx"
            ),
        ),
    ]
