"""仅用于已确认的 HT26011 第二条管材名称更正；默认预检，不改变业务数量。"""

from copy import copy, deepcopy
from decimal import Decimal
import hashlib
import json
from uuid import UUID

from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from apps.audit.models import AuditLog
from apps.core.audit import write_audit_log
from apps.inventory.models import MaterialInboundLine, InternalSemiFinishedReceiptLine, PublicStockBalance, PublicStockMovement
from apps.inventory.public_stock_cutover import lock_stock_writes, require_business_stock_write, require_cutover_operator
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock, debit_public_stock
from apps.inventory.services import _material_search_text
from apps.inventory.tube_outsourcing_reservations import reserved_quantity_for_balance
from apps.material_issues.models import MaterialIssueLine, MetalProcessingSource, OrderSemiFinishedRequirement
from apps.material_issues.processing_selectors import digest, frozen_source
from apps.organizations.models import Employee
from apps.outsourcing.models import TubeOutsourcingOrder
from apps.procurement.models import PurchaseOrderLine, SupplierPurchaseSheet
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.reference_data.pinyin_search import build_pinyin_search

from .models import Bom, BomLine


OLD_NAME = "上下短脚管"
NEW_NAME = "中交上下管"
TASK_ID = "efe154c3-4c1f-4167-9aeb-b3eb62744ca3"
PRODUCT_ID = "954d0836-ec23-4db5-88a7-5d6bffceff03"
BOM_ID = "148af387-dccd-4b6e-b646-89ee1e291220"
LINE_ID = "f617c6fa-20ed-4a9f-b04d-69c8657093db"
PEER_ID = "8a1b22e5-fca7-4e39-b68d-cd2f26210301"
COMPONENT_ID = "5a2d038d-f453-4e46-a395-45176a54cc5f"
PURCHASE_ID = "e02f5d13-c8a4-426a-a75e-1b89d89861f2"
INBOUND_ID = "ffe04da8-e252-4a94-817d-d81548766cfa"
ISSUE_ID = "25c7f162-85e6-4c3f-98cd-947594dbf854"
REQUIREMENT_ID = "31186ae3-a977-5de3-bcb3-9aaae18ec867"
RECEIPT_ID = "cba429a6-4e74-4fb2-9469-63d952180df6"
MOVEMENT_ID = "279281a2-7fbd-41d4-bf91-185ce4630f6f"
BALANCE_ID = "f0faac42-8b34-4ab7-9ae6-f31fee86e696"
OLD_KEY = "b2a154b4599d42e18c6106ae73a45ddede9b86709026e0fffc8aab53df0cda64"
CORRECTION_ID = UUID("a436a63c-7b3c-4b22-9060-d606de129a17")
SOURCE_TYPE = "BOM_COMPONENT_RECLASSIFY"
AUDIT_TYPE = "HT26011_COMPONENT_CORRECTION"
QUANTITY = Decimal(2000)


def require(condition, message):
    if not condition:
        raise CommandError(f"HT26011 更正已阻断：{message}")


def json_value(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False))


def record(instance):
    return json_value({field.attname: getattr(instance, field.attname) for field in instance._meta.concrete_fields})


def manifest_hash(value):
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def rename_fields(fields):
    require(isinstance(fields, list), "名称属性列表缺失。")
    result = deepcopy(fields)
    selected = [item for item in result if isinstance(item, dict) and item.get("key") == "part_name"]
    require(len(selected) == 1 and selected[0].get("value") == OLD_NAME, "名称属性不是唯一的原名称。")
    selected[0]["value"] = NEW_NAME
    return result


def rename_material_attributes(snapshot):
    require(isinstance(snapshot, dict), "采购／入库属性快照缺失。")
    result = deepcopy(snapshot)
    result["fields"] = rename_fields(result.get("fields"))
    return result


def rename_conversion(snapshot):
    require(isinstance(snapshot, dict) and snapshot.get("part_name") == OLD_NAME, "领料名称快照已变化。")
    require(snapshot.get("bom_line_id") == LINE_ID and snapshot.get("component_identity") == COMPONENT_ID,
            "领料快照的来源部位不匹配。")
    result = deepcopy(snapshot)
    frozen = result.get("public_bom_snapshot", {}).get("line", {})
    require(frozen.get("id") == LINE_ID and frozen.get("part_name") == OLD_NAME, "领料冻结 BOM 来源不匹配。")
    result["part_name"] = frozen["part_name"] = NEW_NAME
    result["bom_attributes"] = rename_fields(result.get("bom_attributes"))
    return result


def rename_sheet_content(content):
    require(isinstance(content, dict) and isinstance(content.get("lines"), list), "供应商采购表快照无效。")
    result = deepcopy(content)
    selected = [row for row in result["lines"] if row.get("source_purchase_order_line_id") == PURCHASE_ID]
    require(len(selected) == 1 and selected[0].get("part_name") == OLD_NAME, "采购表目标行缺失、重复或已改名。")
    selected[0]["part_name"] = NEW_NAME
    selected[0]["material_attributes_snapshot"] = rename_material_attributes(selected[0].get("material_attributes_snapshot"))
    return result


def load_plan(*, lock=False):
    """按精确 ID 和当前关联建立预检；apply 在同一事务内重新建立并核对摘要。"""
    evidence = []

    def one(model, pk, related=()):
        query = model.objects.select_related(*related)
        if lock:
            query = query.select_for_update(of=("self",))
        item = query.filter(pk=pk).first()
        require(item is not None, f"{model.__name__} {pk} 不存在。")
        evidence.append({"model": item._meta.label, "record": record(item)})
        return item

    task = one(ProductionTask, TASK_ID)
    product = one(ProductionTaskProduct, PRODUCT_ID)
    bom = one(Bom, BOM_ID)
    line = one(BomLine, LINE_ID, ("section",))
    peer = one(BomLine, PEER_ID, ("section",))
    require(task.task_number == "HT26011" and str(product.production_task_id) == TASK_ID
            and str(bom.product_line_id) == PRODUCT_ID and bom.status == "VERIFIED", "任务、产品或 BOM 状态已变化。")
    latest = Bom.objects.filter(product_line=product, archived_at__isnull=True).order_by("-version_number", "-id").first()
    require(latest is not None and latest.pk == bom.pk, "目标已不是该产品最新 BOM。")
    require(product.product_name_snapshot == "靠背凳" and product.quantity == 2000 and bom.order_quantity == 2000,
            "产品或订单数量已变化。")
    require(str(line.section.bom_id) == BOM_ID and str(peer.section.bom_id) == BOM_ID
            and str(line.component_identity) == COMPONENT_ID and line.line_number == 2
            and peer.line_number == 1 and line.part_name == peer.part_name == OLD_NAME, "BOM 两行来源或名称已变化。")
    for item in (line, peer):
        require(item.cutting_length_mm == 530 and item.pieces_per_product == 2 and item.pieces_per_bar == 5
                and item.raw_bar_length_m == Decimal("2.70") and item.suggested_bar_count == 808
                and item.suggested_purchase_meters == Decimal("2181.60"), "BOM 切割或采购数量已变化。")
    require(not TubeOutsourcingOrder.objects.filter(product_line=product).exists(), "该产品已有管材外发单。")
    require(not OrderSemiFinishedRequirement.objects.filter(product_line=product, component_identity=line.component_identity).exists(),
            "该部位已有半成品领料需求，须另行核对。")
    purchase = one(PurchaseOrderLine, PURCHASE_ID, ("purchase_order",))
    inbound = one(MaterialInboundLine, INBOUND_ID, ("inbound",))
    issue = one(MaterialIssueLine, ISSUE_ID, ("issue__product_line", "requirement"))
    receipt = one(InternalSemiFinishedReceiptLine, RECEIPT_ID, ("receipt__completed_craft", "unit"))
    movement = one(PublicStockMovement, MOVEMENT_ID)
    balance = one(PublicStockBalance, BALANCE_ID, ("zone", "unit"))
    for model, pk in ((type(purchase.purchase_order), purchase.purchase_order_id), (type(inbound.inbound), inbound.inbound_id),
                      (type(issue.issue), issue.issue_id), (type(issue.requirement), issue.requirement_id),
                      (type(receipt.receipt), receipt.receipt_id)):
        one(model, pk)
    require(str(purchase.bom_line_id) == LINE_ID and str(inbound.purchase_order_line_id) == PURCHASE_ID
            and str(issue.requirement_id) == REQUIREMENT_ID and str(issue.requirement.component_identity) == COMPONENT_ID
            and str(receipt.bom_line_id) == LINE_ID and str(receipt.input_requirement_id) == REQUIREMENT_ID
            and str(receipt.stock_movement_id) == MOVEMENT_ID and str(movement.balance_id) == BALANCE_ID,
            "跨流程关联已变化。")
    require(purchase.purchase_order.status == "COMPLETED" and inbound.inbound.status == "CONFIRMED"
            and issue.issue.status == "ISSUED", "采购、入库或领料状态已变化。")
    require(purchase.actual_bar_count == inbound.accepted_bar_count == 808
            and purchase.actual_purchase_meters == inbound.accepted_quantity == Decimal("2181.60")
            and issue.issued_quantity == issue.requested_quantity == 2020
            and receipt.quantity == movement.quantity == QUANTITY, "关联业务数量已变化。")
    require(balance.identity_key == OLD_KEY and balance.quantity == QUANTITY * 2
            and balance.quality == "AVAILABLE" and reserved_quantity_for_balance(balance) == 0, "原半成品余额或预留已变化。")
    require(not MaterialIssueLine.objects.filter(conversion_snapshot__public_identity__identity_key=OLD_KEY,
                issue__status__in=["DRAFT", "PENDING_REVIEW"]).exists(), "原半成品存在待处理领料占用。")
    old_movements = list(balance.movements.order_by("occurred_at", "id"))
    require(len(old_movements) == 2 and {str(row.bom_line_id) for row in old_movements} == {LINE_ID, PEER_ID}
            and all(row.direction == "IN" and row.source_type == "INTERNAL_SEMI_RECEIPT" and row.quantity == QUANTITY
                    for row in old_movements), "原半成品库存不再仅由两条各 2000 支入库组成。")
    require(old_movements[0].before_quantity == 0 and old_movements[0].after_quantity == 2000
            and old_movements[1].before_quantity == 2000 and old_movements[1].after_quantity == 4000, "原库存流水链不完整。")
    evidence.extend({"model": row._meta.label, "record": record(row)} for row in old_movements)
    receipts = list(InternalSemiFinishedReceiptLine.objects.filter(bom_line_id__in=[LINE_ID, PEER_ID]).order_by("id"))
    require(len(receipts) == 2 and all(row.quantity == QUANTITY and row.attribute_snapshot == balance.identity_snapshot
                                     for row in receipts), "两条部位入库历史或属性已变化。")
    evidence.extend({"model": row._meta.label, "record": record(row)} for row in receipts)
    new_line = copy(line)
    new_line.part_name = NEW_NAME
    identity = build_semi_finished_identity(bom_line=new_line, completed_craft=receipt.receipt.completed_craft, unit=receipt.unit)
    expected_attributes = deepcopy(balance.identity_snapshot)
    expected_attributes["part_name"] = NEW_NAME
    require(identity["identity_snapshot"] == expected_attributes, "新旧半成品身份除名称外存在差异。")
    require(not PublicStockBalance.objects.filter(stock_kind="SEMI", identity_key=identity["identity_key"]).exists(),
            "新名称已有半成品库存，不能自动合并。")
    changes = [(line, {"part_name": NEW_NAME})]
    for item in (purchase, inbound):
        require(item.part_name_snapshot == OLD_NAME, "采购或入库名称已变化。")
        changes.append((item, {"part_name_snapshot": NEW_NAME,
                              "material_attributes_snapshot": rename_material_attributes(item.material_attributes_snapshot)}))
    inbound_copy = copy(inbound)
    for field, value in changes[-1][1].items():
        setattr(inbound_copy, field, value)
    changes[-1][1]["material_pinyin_search"] = build_pinyin_search(_material_search_text(inbound_copy))
    conversion = rename_conversion(issue.conversion_snapshot)
    require(issue.material_name_snapshot == OLD_NAME, "领料显示名称已变化。")
    changes.append((issue, {"conversion_snapshot": conversion, "material_name_snapshot": NEW_NAME}))
    # 冻结来源严格比较领料与实际出库流水，必须同时更正名称，数量及原料身份保持不动。
    original_frozen = frozen_source(issue)
    allocations = list(issue.public_stock_allocations.select_related("movement", "balance").order_by("id"))
    require(sum(row.stock_quantity for row in allocations) == 404, "实际原料出库不再为 404 根。")
    for allocation in allocations:
        stock_movement = one(PublicStockMovement, allocation.movement_id)
        one(PublicStockBalance, allocation.balance_id)
        evidence.append({"model": allocation._meta.label, "record": record(allocation)})
        value = deepcopy(stock_movement.snapshot)
        require(value.get("conversion") == issue.conversion_snapshot, "原料出库与领料快照不一致。")
        value["conversion"] = conversion
        changes.append((stock_movement, {"snapshot": value}))
    sources = list(MetalProcessingSource.objects.filter(issue_line=issue))
    if sources:
        source = one(MetalProcessingSource, sources[0].pk)
        require(source.source_snapshot == original_frozen and source.source_hash == digest(original_frozen), "金工来源冻结资料已变化。")
        require(source.reserved_pieces == source.dispatched_pieces == 0 and not source.original_handoffs.exists()
                and not source.p4_external_orders.exists(), "已有金工交接或外发，需要扩大核对范围。")
        corrected_frozen = deepcopy(original_frozen)
        corrected_frozen["part_name"] = NEW_NAME
        corrected_frozen["conversion_snapshot"] = conversion
        changes.append((source, {"source_snapshot": corrected_frozen, "source_hash": digest(corrected_frozen),
                                 "version": source.version + 1}))
    changes.append((receipt, {"attribute_snapshot": identity["identity_snapshot"]}))
    sheets = []
    for candidate in SupplierPurchaseSheet.objects.filter(purchase_order_id=purchase.purchase_order_id).order_by("id"):
        rows = candidate.content_snapshot.get("lines", [])
        if any(row.get("source_purchase_order_line_id") == PURCHASE_ID for row in rows):
            sheet = one(SupplierPurchaseSheet, candidate.pk)
            require(sheet.status == "PUBLISHED", "关联供应商采购表状态已变化。")
            sheets.append(sheet)
            changes.append((sheet, {"content_snapshot": rename_sheet_content(sheet.content_snapshot)}))
    require(len(sheets) == 1, "应存在唯一一张关联第二条部位的已发布采购表。")
    # 使打开的 BOM/领料编辑器持有的旧版本失效；不改业务状态或版本号语义。
    changes.extend([(bom, {}), (purchase.purchase_order, {}), (inbound.inbound, {}),
                    (receipt.receipt, {}), (issue.issue, {"version": issue.issue.version + 1})])
    payload = {"correction_id": str(CORRECTION_ID), "evidence": evidence,
               "changes": [{"model": obj._meta.label, "id": str(obj.pk), "fields": values} for obj, values in changes],
               "new_identity": identity, "transfer_quantity": QUANTITY}
    return {"changes": changes, "payload": json_value(payload), "manifest_sha256": manifest_hash(payload),
            "balance": balance, "identity": identity, "task": task, "product": product, "line": line,
            "issue": issue, "receipt": receipt}


def summary(plan):
    return {"status": "DRY_RUN", "correction_id": str(CORRECTION_ID), "manifest_sha256": plan["manifest_sha256"],
            "bom_line_id": LINE_ID, "old_name": OLD_NAME, "new_name": NEW_NAME, "transfer_quantity": "2000",
            "old_identity_key": plan["balance"].identity_key, "new_identity_key": plan["identity"]["identity_key"],
            "changes": [{"model": obj._meta.label, "id": str(obj.pk), "fields": list(values)} for obj, values in plan["changes"]]}


@transaction.atomic
def correct_component(*, apply=False, actor_id=None, expected_manifest=""):
    if apply:
        require(actor_id and expected_manifest, "--apply 必须同时提供 --actor-employee 和 --expected-manifest。")
        actor = require_cutover_operator(Employee.objects.filter(pk=actor_id).first())
        # 独占库存事务锁只持有本次短事务，避免校验后其他订单占用待拆分库存。
        lock_stock_writes(exclusive=True)
        require_business_stock_write()
    previous = AuditLog.objects.filter(object_type=AUDIT_TYPE, object_id=CORRECTION_ID, action="CORRECTED").first()
    if previous:
        movements = list(PublicStockMovement.objects.filter(source_type=SOURCE_TYPE, source_id=CORRECTION_ID))
        require(len(movements) == 2 and {row.direction for row in movements} == {"IN", "OUT"}
                and all(row.quantity == QUANTITY for row in movements), "已有更正审计但配对库存流水不完整。")
        saved_movements = previous.after_data.get("movements", [])
        require({row["id"] for row in saved_movements} == {str(row.pk) for row in movements}
                and all(record(row) in saved_movements for row in movements), "更正流水与原更正审计不一致。")
        require(BomLine.objects.filter(pk=LINE_ID, part_name=NEW_NAME).exists(), "已有更正审计但 BOM 名称不一致。")
        return {"status": "ALREADY_APPLIED", "correction_id": str(CORRECTION_ID), "audit_id": str(previous.pk)}
    plan = load_plan(lock=apply)
    result = summary(plan)
    if not apply:
        return result
    require(plan["manifest_sha256"] == expected_manifest, "来源与已审阅预检不一致，请重新 dry-run。")
    before = plan["payload"]
    for instance, values in plan["changes"]:
        for field, value in values.items():
            setattr(instance, field, value)
        instance.save(update_fields=[*values, "updated_at"])
    frozen_source(MaterialIssueLine.objects.select_related("issue__product_line", "requirement").get(pk=plan["issue"].pk))
    source = {"source_type": SOURCE_TYPE, "source_id": CORRECTION_ID, "source_line_id": CORRECTION_ID,
              "actor_employee": actor, "production_task": plan["task"], "product_line": plan["product"], "bom_line": plan["line"],
              "snapshot": {"reason": "用户确认 HT26011 第二条上下短脚管应为中交上下管，数量不变",
                           "correction_id": str(CORRECTION_ID), "original_receipt_line_id": RECEIPT_ID,
                           "original_movement_id": MOVEMENT_ID, "old_identity_key": OLD_KEY,
                           "new_identity": plan["identity"]}}
    source["snapshot"] = json_value(source["snapshot"])
    outgoing = debit_public_stock(balance_id=plan["balance"].pk, quantity=QUANTITY, **source)
    incoming = credit_public_stock(identity=plan["identity"], zone=plan["balance"].zone, quantity=QUANTITY, **source)
    require(outgoing.after_quantity == incoming.after_quantity == QUANTITY, "拆分后库存不是各 2000 支。")
    for item in before["evidence"]:
        saved = item["record"]
        if item["model"] == "inventory.PublicStockBalance" and saved["stock_kind"] == "RAW_PIPE":
            require(record(PublicStockBalance.objects.get(pk=saved["id"])) == saved, "原料库存发生意外变化，整笔回滚。")
    # 审计保存数据库定标后的完整流水，避免 2000 与 2000.0000 造成重放误判。
    outgoing.refresh_from_db()
    incoming.refresh_from_db()
    after = {"records": [{"model": obj._meta.label, "record": record(obj)} for obj, _ in plan["changes"]],
             "movements": [record(outgoing), record(incoming)], "new_identity": json_value(plan["identity"]),
             "pdf_files_preserved": True}
    audit = write_audit_log(object_type=AUDIT_TYPE, object_id=CORRECTION_ID, action="CORRECTED", actor_employee=actor,
                            before_data=before, after_data=after, context_type="BOM", context_id=plan["line"].section.bom_id)
    return {**result, "status": "APPLIED", "audit_id": str(audit.pk),
            "movement_ids": [str(outgoing.pk), str(incoming.pk)], "new_balance_id": str(incoming.balance_id)}
