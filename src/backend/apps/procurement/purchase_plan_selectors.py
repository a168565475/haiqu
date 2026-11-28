from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from apps.boms.models import Bom, BomLine, BomStatus
from apps.core.delivery_reminders import BEIJING, matching_reminder, reminder_matches, reminder_order
from apps.inventory.bom_inventory_sections import RAW_SECTIONS
from apps.inventory.purchase_receiving_sections import with_receiving_section
from apps.production_tasks.models import ProductionTask
from apps.products.material_identity import DIRECT_RAW_MATERIAL_SOURCE_KEYS

from .material_attribute_snapshot import build_material_attribute_snapshot
from .models import PurchaseGroupLine, PurchaseOrderLine, PurchaseScope
from .purchase_plan_receipts import amount, purchase_plan_batches, purchase_plan_totals
from .purchase_plan_reminders import purchase_shortfalls, scheduled_material_dates
from .purchase_scope import packaging_order_filter
from .services import _is_purchasable_bom_section, _source_quantity
from .tracking_rules import decimal_value
from .tracking_policy import get_tracking_policy
from .tracking_selectors import VALID_PURCHASE_STATUSES


@dataclass(frozen=True)
class DemandSource:
    task_id: UUID
    bom_id: UUID | None
    product_id: UUID | None
    line_id: UUID


def _uuid(value):
    try:
        return UUID(str(value)) if value else None
    except (ValueError, TypeError):
        return None


def _category(snapshot):
    selection = snapshot.get("material_selection_snapshot") or {}
    if not isinstance(selection, dict):
        return None
    if selection.get("processing_state") == "PROCESSED" or selection.get("template_key") in {"COTTON", "AUXILIARY_GENERAL"}:
        return None
    if snapshot.get("section_title_snapshot") == "裁剪明细":
        return None
    if key := selection.get("category_key"):
        return key
    if snapshot.get("section_type_snapshot") == "PROFILE":
        return "TUBE"
    for field in ("section_title_snapshot", "category_snapshot"):
        for category, (_, aliases) in RAW_SECTIONS.items():
            if snapshot.get(field) in aliases:
                return category
    return None


def _bom_snapshot(line):
    needed, _, _, unit, status = _source_quantity(line, line.section.bom)
    return {
        "category_snapshot": line.category, "section_title_snapshot": line.section.title,
        "section_type_snapshot": line.section.section_type, "specification_snapshot": line.specification,
        "material_snapshot": line.material, "part_name_snapshot": line.part_name, "raw_material_snapshot": line.raw_material,
        "material_selection_snapshot": line.material_selection_snapshot,
        "material_attributes_snapshot": build_material_attribute_snapshot(line, line.section),
        "required_quantity": needed if status == "READY" else None, "source_unit_text": unit,
        "raw_bar_length_m": line.raw_bar_length_m,
    }


def _original_sources(record, task_id):
    for row in record:
        if isinstance(row, dict) and (line_id := _uuid(row.get("bom_line_id") or row.get("source_bom_line_id_snapshot"))):
            yield DemandSource(task_id, _uuid(row.get("bom_id")),
                               _uuid(row.get("product_line_id") or row.get("product_line_id_snapshot")), line_id), row


def _purchase_snapshot(line):
    fields = (
        "category_snapshot", "section_title_snapshot", "section_type_snapshot", "specification_snapshot",
        "material_snapshot", "part_name_snapshot", "raw_material_snapshot", "material_selection_snapshot",
        "material_attributes_snapshot", "required_quantity", "source_unit_text", "raw_bar_length_m",
        "calculation_snapshot",
    )
    return {field: getattr(line, field) for field in fields}


def _source_index(tasks, category):
    latest = Bom.objects.filter(product_line_id=OuterRef("section__bom__product_line_id"), archived_at__isnull=True)
    latest = latest.order_by("-version_number", "-pk").values("pk")[:1]
    aliases = RAW_SECTIONS[category][1]
    candidates = Q(material_selection_snapshot__category_key=category) | Q(section__title__in=aliases) | Q(category__in=aliases)
    if category == "TUBE":
        candidates |= Q(section__section_type="PROFILE")
    current = BomLine.objects.filter(
        candidates, section__bom__production_task_id__in=tasks,
        section__bom_id=Subquery(latest), section__bom__status=BomStatus.VERIFIED,
    ).select_related("section__bom").order_by()
    snapshots = {}
    for line in current:
        if not line.purchase_required or not _is_purchasable_bom_section(line.section):
            continue
        snapshot = _bom_snapshot(line)
        if _category(snapshot) == category:
            bom = line.section.bom
            snapshots[DemandSource(bom.production_task_id, bom.pk, bom.product_line_id, line.pk)] = snapshot
    current_lines = {source.line_id for source in snapshots}

    frozen = PurchaseGroupLine.objects.filter(
        purchase_group__production_task_id__in=tasks, purchase_group__archived_at__isnull=True,
        purchase_group__purchase_scope=PurchaseScope.STANDARD,
    ).select_related("purchase_group").order_by("purchase_group__created_at", "line_number", "pk")
    frozen_by_source = {}
    for line in frozen:
        snapshot = line.source_snapshot
        if not isinstance(snapshot, dict) or snapshot.get("purchase_required") is False or _category(snapshot) != category:
            continue
        contributions = snapshot.get("source_contributions") or [{
            "bom_line_id": line.source_bom_line_id_snapshot, "bom_id": snapshot.get("bom_id"),
            "product_line_id": line.product_line_id_snapshot,
            "source_snapshot": {**snapshot, "required_quantity": line.required_quantity, "source_unit_text": line.source_unit_text},
        }]
        for source, contribution in _original_sources(contributions, line.purchase_group.production_task_id):
            original = contribution.get("source_snapshot") or {}
            if original and original.get("purchase_required") is not False:
                frozen_by_source.setdefault(source, original)
    snapshots.update(frozen_by_source)

    purchases = with_receiving_section(PurchaseOrderLine.objects.filter(
        ~packaging_order_filter("purchase_order__"),
        purchase_order__production_task_id__in=tasks, purchase_order__source_type="PRODUCTION",
        purchase_order__archived_at__isnull=True, purchase_order__status__in=VALID_PURCHASE_STATUSES,
    )).filter(receiving_section=category).select_related("purchase_order__production_task").order_by(
        "purchase_order__created_at", "purchase_order_id", "line_number", "pk",
    )
    batches = []
    for line in purchases:
        saved = _purchase_snapshot(line)
        if _category(saved) != category:
            continue
        multi = (line.calculation_snapshot or {}).get("group_source_contributions")
        links = multi or [{
            "bom_line_id": line.source_bom_line_id_snapshot or line.bom_line_id,
            "bom_id": line.bom_id, "product_line_id": line.product_line_id_snapshot,
        }]
        linked = dict(_original_sources(links, line.purchase_order.production_task_id))
        for source, contribution in linked.items():
            if source not in snapshots:
                snapshots[source] = ({**saved, "required_quantity": contribution.get("required_quantity"),
                                      "source_unit_text": contribution.get("source_unit_text"),
                                      "component_identity": contribution.get("component_identity")} if multi else saved)
        batches.append((line, list(linked), bool(multi and (len(links) != 1 or not linked))))
    return snapshots, batches, frozen_by_source, current_lines


def _requirement(source, snapshot, bom, line):
    saved_attributes = {field["key"]: field["value"] for field in
                        (snapshot.get("material_attributes_snapshot") or {}).get("fields", [])}
    selection = snapshot.get("material_selection_snapshot") or {}
    selected = selection.get("attributes") or {}
    raw = line.raw_values if line and isinstance(line.raw_values, dict) else {}
    calculation = snapshot.get("calculation_snapshot") or {}
    component_id = line.component_identity if line else _uuid(snapshot.get("component_identity") or calculation.get("component_identity"))
    raw_id = calculation.get("raw_material_id") or next((raw[key] for key in DIRECT_RAW_MATERIAL_SOURCE_KEYS if raw.get(key)), "")
    raw_length = decimal_value(snapshot.get("raw_bar_length_m"))
    cutting_length = calculation.get("cutting_length_mm")
    required_unit = snapshot.get("source_unit_text") or ""
    quantity = decimal_value(snapshot.get("required_quantity"))
    name = snapshot.get("part_name_snapshot") or snapshot.get("material_snapshot") or ""
    material = snapshot.get("material_snapshot") or selected.get("material") or ""
    return {
        "id": source.line_id, "task_id": source.task_id, "task_number": bom.production_task.task_number,
        "product_name": bom.product_name_snapshot or bom.product_line.product_name_snapshot,
        "task_quantity": bom.order_quantity, "bom_number": bom.bom_number,
        "name": name, "material": material,
        "specification": snapshot.get("specification_snapshot") or selected.get("fabric_spec") or selected.get("section_size") or "",
        "thickness": saved_attributes.get("tube_thickness") or selected.get("thickness") or raw.get("tube_thickness") or raw.get("G") or "",
        "cutting_length": str(cutting_length or (line.cutting_length_mm or line.length_value if line else "") or ""),
        "raw_length": str(raw_length) if raw_length is not None else "",
        "hardness": line.hardness if line else "",
        "coating": saved_attributes.get("fabric_coating") or selected.get("finish") or raw.get("fabric_coating")
                   or raw.get("涂层") or selected.get("coating") or "",
        "fabric_width": saved_attributes.get("fabric_width") or selected.get("width") or raw.get("fabric_width") or "",
        "fabric_color": saved_attributes.get("fabric_color_name") or selected.get("color") or raw.get("fabric_color_name") or "",
        "required": amount(quantity, required_unit), "_required_unit": required_unit, "note": "",
        "_version": bom.version_number, "_bom": bom,
        "_component": (source.task_id, bom.product_line_id, component_id) if component_id else None,
        "_selection": (tuple(str(selection.get(field) or "") for field in
                            ("catalog_id", "unit_id", "product_color_id", "color_card", "color_code")),
                       tuple(sorted((key, str(value)) for key, value in selected.items())))
                      if selection.get("catalog_id") else ("raw", str(raw_id or snapshot.get("raw_material_snapshot") or "")),
    }


def _bom_revisions(rows):
    components = defaultdict(list)
    for row in rows.values():
        components[row["_component"] or row["id"]].append(row)
    canonical, sources = {}, {}
    for versions in components.values():
        materials = defaultdict(list)
        for row in versions:
            identity = (row["_selection"], *(row[field] for field in (
                "_required_unit", "material", "specification", "thickness", "hardness", "coating", "fabric_width", "fabric_color",
            )), decimal_value(row["raw_length"]))
            materials[identity].append(row)
        for same_material in materials.values():
            same_material.sort(key=lambda row: (row["_version"], row["id"]))
            latest = same_material[-1]
            sources[latest["id"]] = [{"bom_number": row["bom_number"], "required": row["required"]} for row in same_material]
            quantities = {decimal_value(row["required"]["quantity"]) if row["required"] else None for row in same_material}
            latest["_quantity_changed"] = len(quantities) > 1
            if len(materials) > 1:
                latest["note"] = "BOM 物料变更，待核对"
            elif latest["_quantity_changed"]:
                latest["note"] = "BOM 用量变更，待核对"
            canonical.update((row["id"], latest["id"]) for row in same_material)
    return canonical, sources


def purchase_plan(*, task_ids, category, task_number="", q="", page=1, page_size=20, line_id=None, follow_up="ALL", owner=""):
    tasks = ProductionTask.objects.filter(pk__in=task_ids).exclude(status__in=("DRAFT", "PENDING_VALIDATION"))
    if task_number:
        tasks = tasks.filter(task_number__icontains=task_number)
    task_ids = list(tasks.values_list("pk", flat=True))
    snapshots, purchases, frozen, current_lines = _source_index(task_ids, category)
    originals = BomLine.objects.filter(pk__in={source.line_id for source in snapshots},
                                       section__bom__production_task_id__in=task_ids)
    originals = {line.pk: line for line in originals.select_related("section")}
    bom_ids = {source.bom_id for source in snapshots} | {line.section.bom_id for line in originals.values()}
    boms = {bom.pk: bom for bom in Bom.objects.filter(pk__in=bom_ids, production_task_id__in=task_ids)
            .select_related("product_line", "production_task")}

    rows, source_keys, ranks = {}, {}, {}
    for source, snapshot in snapshots.items():
        original = originals.get(source.line_id)
        bom = boms.get(source.bom_id or (original.section.bom_id if original else None))
        if (bom is None or bom.production_task_id != source.task_id
                or bom.product_line.production_task_id != source.task_id
                or (source.product_id is not None and source.product_id != bom.product_line_id)
                or (original and original.section.bom_id != bom.pk)):
            continue
        source_keys[source] = source.line_id
        rank = (source in frozen, source.bom_id is not None)
        if source.line_id not in rows or rank > ranks[source.line_id]:
            rows[source.line_id] = _requirement(source, snapshot, bom, original)
            ranks[source.line_id] = rank

    canonical, source_versions = _bom_revisions(rows)
    batches_by_source = defaultdict(list)
    shared, origins_by_batch, unknown_tasks = set(), {}, set()
    for purchase, links, is_shared in purchases:
        originals = [source_keys[link] for link in links if link in source_keys]
        keys = list(dict.fromkeys(canonical[key] for key in originals))
        if not keys:
            unknown_tasks.add(purchase.purchase_order.production_task_id)
        if is_shared or len(keys) > 1:
            shared.add(purchase.pk)
        origins_by_batch[purchase.pk] = {
            "products": list(dict.fromkeys(rows[key]["product_name"] for key in keys)),
            "bom_numbers": list(dict.fromkeys(rows[key]["bom_number"] for key in originals)),
        }
        for key in keys:
            batches_by_source[key].append(purchase)

    keyword = q.casefold()
    matches = [row for row in rows.values() if canonical[row["id"]] == row["id"] and (line_id is None or row["id"] == line_id)
               and any(keyword in row[key].casefold() for key in ("name", "material", "specification"))]
    if not matches:
        return [], 0
    now = timezone.now().astimezone(BEIJING)
    policy = get_tracking_policy()
    schedule_dates = scheduled_material_dates(matches) if policy is not None else {}
    current_purchases = {purchase.pk: purchase for row in matches for purchase in batches_by_source[row["id"]]}
    detailed = purchase_plan_batches(list(current_purchases.values()), origins_by_batch, shared, today=now.date(),
                                     details=line_id is not None)
    selected = []
    for row in matches:
        batches = [detailed[purchase.pk] for purchase in batches_by_source[row["id"]]]
        shortages = []
        if row["id"] in current_lines:
            shortages = purchase_shortfalls(row, batches, now=now, category=category, schedule_dates=schedule_dates,
                                           policy=policy, unlinked=row["task_id"] in unknown_tasks)
        row["reminder"] = matching_reminder([*shortages, *(batch["reminder"] for batch in batches)], follow_up, owner)
        if not reminder_matches(row["reminder"], follow_up, owner):
            continue
        row["ordered"], row["received"], row["progress"] = purchase_plan_totals(batches, row["_required_unit"])
        if row["task_id"] in unknown_tasks and not batches:
            row.update(ordered=[], received=[], progress="采购归属待核对")
        if line_id is not None:
            row["batches"] = batches
            row["source_versions"] = source_versions[row["id"]]
            row["purchase_reminders"] = shortages
        selected.append(row)
    selected.sort(key=lambda row: (*reminder_order(row["reminder"]), row["task_number"], row["product_name"],
                                   row["bom_number"], row["name"], row["specification"], row["id"]))
    start = (page - 1) * page_size
    return selected[start:start + page_size], len(selected)
