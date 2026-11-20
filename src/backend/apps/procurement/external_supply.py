"""确认 BOM 后，只同步本 BOM 的采购/外供选择，保留已确认单据的履约记录。"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q

from apps.boms.models import Bom, BomLine
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from .group_services import _save_bom_snapshot, bom_group_line_snapshot, save_bom_group_line
from .multi_bom_sources import merge_purchase_snapshots, purchase_merge_key
from .models import PurchaseGroup, PurchaseGroupLine, PurchaseOrder, PurchaseOrderStatus, PurchaseRequest, PurchaseRequestStatus
from .services import _is_purchasable_bom_section, _source_line


def _remove_external_draft_lines(order, lines, external_ids, external_group_lines):
    removed = [
        line for line in lines if line.purchase_group_line_id in external_group_lines
        or (not (line.calculation_snapshot or {}).get("group_source_contributions")
            and (line.source_bom_line_id_snapshot in external_ids or line.bom_line_id in external_ids))
    ]
    if not removed:
        return []
    removed_ids = {line.pk for line in removed}
    remaining = [line for line in lines if line.pk not in removed_ids]
    affected_sets = {
        pricing["anchor_id"] for line in removed
        if (pricing := (line.calculation_snapshot or {}).get("set_pricing"))
    }
    for anchor in affected_sets:
        survivors = [line for line in remaining if (line.calculation_snapshot or {}).get("set_pricing", {}).get("anchor_id") == anchor]
        if len(survivors) >= 2 and any(str(line.purchase_group_line_id) == anchor for line in survivors):
            continue
        for line in survivors:
            line.calculation_snapshot.pop("set_pricing")
            line.calculation_snapshot["set_pricing_review"] = "外供调整"
            line.unit_price = line.amount = None
            line.save(update_fields=["calculation_snapshot", "unit_price", "amount"])
    order.lines.filter(pk__in=removed_ids).delete()
    amounts = [line.amount for line in remaining if (
        not (pricing := (line.calculation_snapshot or {}).get("set_pricing"))
        or pricing["anchor_id"] == str(line.purchase_group_line_id)
    )]
    order.total_amount = sum(amounts, Decimal("0")) if amounts and None not in amounts else None
    order.save(update_fields=["total_amount", "updated_at"])
    return removed_ids


@dataclass
class _CombinedMaterial:
    row: PurchaseGroupLine | None = None
    active: list[dict] = field(default_factory=list)
    external: list[dict] = field(default_factory=list)
    changed: bool = False


def _sync_combined_group(group, bom, choices, previous_group_id):
    rows = list(group.lines.select_for_update().order_by("line_number"))
    by_material, by_bom_line, by_component = {}, {}, {}
    for row in rows:
        saved = row.source_snapshot
        active = [c["source_snapshot"] for c in saved["source_contributions"]]
        external = list(saved.get("external_source_snapshots", []))
        state = _CombinedMaterial(row, active, external)
        by_material[purchase_merge_key(saved)] = state
        for snapshot in active + external:
            if snapshot["product_line_id_snapshot"] == str(bom.product_line_id):
                by_bom_line[snapshot["bom_line_id"]] = (state, snapshot)
                if component := snapshot.get("component_identity"):
                    by_component[component] = (state, snapshot)
    previous_lines = {}
    if previous_group_id:
        previous_lines = dict(PurchaseGroupLine.objects.filter(purchase_group_id=previous_group_id).values_list("source_bom_line_id_snapshot", "pk"))
    changed_ids = []
    for pk, line in choices.items():
        match = by_bom_line.get(str(pk)) or by_component.get(str(line.component_identity))
        if match:
            state, snapshot = match
            if (snapshot in state.active) == line.purchase_required:
                continue
            if line.purchase_required:
                state.external.remove(snapshot)
                state.active.append(snapshot)
            else:
                state.active.remove(snapshot)
                state.external.append(snapshot)
        elif line.purchase_required:
            snapshot = bom_group_line_snapshot(_source_line(bom, line.section, line, bom.product_line))
            if pk in previous_lines:
                snapshot["previous_group_line_id"] = str(previous_lines[pk])
            key = purchase_merge_key(snapshot)
            state = by_material.get(key)
            if state is None:
                by_material[key] = state = _CombinedMaterial()
            state.active.append(snapshot)
        else:
            continue
        changed_ids.append(str(pk))
        state.changed = True
    next_number = max((row.line_number for row in rows), default=0)
    for state in by_material.values():
        if not state.changed:
            continue
        row, active, external = state.row, state.active, state.external
        saved = merge_purchase_snapshots(active) if active else {
            **row.source_snapshot, "source_contributions": [], "purchase_required": False,
        }
        saved["external_source_snapshots"] = external
        saved["previous_group_line_ids"] = [s["previous_group_line_id"] for s in active + external if s.get("previous_group_line_id")]
        if row:
            row.source_snapshot = saved
            row.required_quantity = Decimal(saved["required_quantity"])
            row.source_bom_line_id_snapshot = saved["source_bom_line_id_snapshot"]
            row.product_line_id_snapshot = saved["product_line_id_snapshot"]
            row.save(update_fields=["source_snapshot", "required_quantity", "source_bom_line_id_snapshot",
                                    "product_line_id_snapshot", "updated_at"])
        else:
            next_number += 1
            _save_bom_snapshot(group, next_number, saved)
    return changed_ids


def sync_external_supply(bom, bom_lines, *, actor_employee, request):
    choices = {line.pk: line for line in bom_lines
               if _is_purchasable_bom_section(line.section) and "purchase_required" in (line.raw_values or {})}
    if not choices or Bom.objects.filter(
        product_line_id=bom.product_line_id, archived_at__isnull=True, version_number__gt=bom.version_number,
    ).exists():
        return
    external_ids = {pk for pk, line in choices.items() if not line.purchase_required}
    if external_ids and bom.version_number > 1:
        external_ids.update(BomLine.objects.filter(
            section__bom__product_line_id=bom.product_line_id, section__bom__version_number__lt=bom.version_number,
            component_identity__in=[choices[pk].component_identity for pk in external_ids],
        ).values_list("pk", flat=True))
    groups = list(PurchaseGroup.objects.select_for_update().filter(
        production_task_id=bom.production_task_id, product_line_id_snapshot=bom.product_line_id,
        archived_at__isnull=True,
    ))
    group = (groups[0] if len(groups) == 1 else
             next((group for group in groups if group.source_bom_id_snapshot == bom.pk), None))
    if group:
        sources = {source.source_bom_line_id_snapshot: source for source in group.lines.all()}
        # 同产品复制时 component_identity 保留，跨产品复制时重建；不能用名称映射冻结行。
        prior_ids = {}
        if group.source_bom_id_snapshot != bom.pk:
            previous = BomLine.objects.filter(
                section__bom_id=group.source_bom_id_snapshot,
                component_identity__in=[line.component_identity for line in choices.values()],
            )
            prior_ids = dict(previous.values_list("component_identity", "pk"))
            prior_ids.update(BomLine.objects.filter(pk__in=sources).values_list("component_identity", "pk"))
        next_number = max((row.line_number for row in sources.values()), default=0)
        changed = []
        for pk, line in choices.items():
            prior_id = prior_ids.get(line.component_identity)
            source = sources.get(pk) or sources.get(prior_id)
            if source is None:
                if not line.purchase_required:
                    continue
                next_number += 1
                save_bom_group_line(group, next_number, _source_line(bom, line.section, line, bom.product_line))
            elif not isinstance(source.source_snapshot, dict):
                raise Conflict(f"采购需求第{source.line_number}行的历史来源待核对，无法同步外供设置。")
            elif source.source_snapshot.get("purchase_required", True) == line.purchase_required:
                continue
            else:
                source.source_snapshot["purchase_required"] = line.purchase_required
                source.save(update_fields=["source_snapshot", "updated_at"])
            changed.append(str(pk))
        if changed:
            group.save(update_fields=["updated_at"])
            write_audit_log(object_type="PURCHASE_GROUP", object_id=group.pk, action="BOM_PURCHASE_SCOPE_UPDATED",
                            context_type="PRODUCTION_TASK", context_id=bom.production_task_id, actor_employee=actor_employee,
                            after_data={"bom_id": str(bom.pk), "changed_bom_line_ids": changed}, request=request)
    combined_groups = PurchaseGroup.objects.select_for_update().filter(
        production_task_id=bom.production_task_id, archived_at__isnull=True, product_line_id_snapshot__isnull=True,
        bom_sources__product_line_id_snapshot=bom.product_line_id,
    ).order_by("pk")
    external_group_lines = set()
    for combined in combined_groups:
        previous = combined.bom_sources.get(product_line_id_snapshot=bom.product_line_id)
        changed = _sync_combined_group(combined, bom, choices, previous.previous_group_id)
        if changed:
            combined.save(update_fields=["updated_at"])
            write_audit_log(object_type="PURCHASE_GROUP", object_id=combined.pk, action="BOM_PURCHASE_SCOPE_UPDATED",
                            context_type="PRODUCTION_TASK", context_id=bom.production_task_id, actor_employee=actor_employee,
                            after_data={"bom_id": str(bom.pk), "changed_bom_line_ids": changed}, request=request)
        if external_ids:
            external_group_lines.update(combined.lines.filter(source_snapshot__purchase_required=False).values_list("pk", flat=True))
    if not external_ids:
        return
    orders = PurchaseOrder.objects.select_for_update().filter(
        production_task_id=bom.production_task_id, status=PurchaseOrderStatus.DRAFT, archived_at__isnull=True,
        pk__in=PurchaseOrder.objects.filter(
            Q(lines__source_bom_line_id_snapshot__in=external_ids) | Q(lines__bom_line_id__in=external_ids)
            | Q(lines__purchase_group_line_id__in=external_group_lines)
        ).values("pk"),
    ).exclude(supplier_purchase_sheets__isnull=False).exclude(material_inbounds__isnull=False).exclude(
        returns__isnull=False,
    ).order_by("pk")
    for order in orders:
        removed = _remove_external_draft_lines(order, list(order.lines.select_for_update()), external_ids, external_group_lines)
        if not removed:
            continue
        write_audit_log(object_type="PURCHASE_ORDER", object_id=order.pk, action="DRAFT_EXTERNAL_LINES_REMOVED",
                        context_type="PRODUCTION_TASK", context_id=bom.production_task_id, actor_employee=actor_employee,
                        after_data={"bom_id": str(bom.pk), "removed_line_ids": [str(pk) for pk in removed]}, request=request)
    for draft in PurchaseRequest.objects.select_for_update().filter(
        production_task_id=bom.production_task_id, status=PurchaseRequestStatus.DRAFT, archived_at__isnull=True,
    ):
        removed, _ = draft.lines.filter(bom_line_id__in=external_ids, allocations__isnull=True).delete()
        if removed:
            draft.save(update_fields=["updated_at"])
            write_audit_log(object_type="PURCHASE_REQUEST", object_id=draft.pk, action="DRAFT_EXTERNAL_LINES_REMOVED",
                            context_type="PRODUCTION_TASK", context_id=bom.production_task_id, actor_employee=actor_employee,
                            after_data={"bom_id": str(bom.pk), "removed_count": removed}, request=request)
