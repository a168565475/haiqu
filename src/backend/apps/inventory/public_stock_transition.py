"""只读列出切换时需处理的旧未结单；不转换余额、不升级历史单据。"""

from collections import Counter

from django.db.models import Exists, OuterRef, Q

from apps.material_issues.models import MaterialIssue, MaterialIssueLine, MetalProcessingExternalOrder, MetalProcessingOriginalHandoff
from apps.outsourcing.models import OutsourcingDispatch, OutsourcingOrder
from .models import MaterialInbound
from .public_stock_mode import public_flow_enabled


def preview_public_stock_transition():
    rows = []

    def add(kind, row, number, code, reason):
        rows.append({"kind": kind, "id": str(row["id"]), "number": row[number],
                     "status": row["status"], "code": code, "reason": reason})

    for row in MaterialInbound.objects.filter(stock_mode="LEGACY", status="PENDING_QUALITY").order_by("id").values("id", "inbound_number", "status"):
        add("MATERIAL_INBOUND", row, "inbound_number", "PENDING_QUALITY_REVIEW",
            "已收货未质检：正式切换前完成质检及期初核对，或单独核验原入库冻结属性后制定接续操作。")
    for row in MaterialIssue.objects.filter(stock_mode="LEGACY", status__in=["DRAFT", "RETURNED", "PENDING_REVIEW"]).order_by("id").values("id", "issue_number", "status"):
        add("MATERIAL_ISSUE", row, "issue_number", "UNISSUED_PLAN_RECREATE",
            "尚未实际出库：按原权限退回或取消旧计划，依据当前有效 BOM 重新建立公共领料单；已领及外发额度继续继承。")
    issued_lines = MaterialIssueLine.objects.filter(
        issue__stock_mode="LEGACY", issue__status="ISSUED", line_type="RAW", conversion_snapshot__kind="PIPE",
    ).filter(Q(processing_source__isnull=True) | Q(processing_source__status="OPEN")).select_related("issue", "processing_source").order_by("id")
    for line in issued_lines:
        source = getattr(line, "processing_source", None)
        rows.append({"kind": "METAL_PROCESSING_SOURCE", "id": str(line.pk), "number": line.issue.issue_number,
                     "status": source.status if source else "NOT_REGISTERED", "code": "ISSUED_RAW_SOURCE_REVIEW",
                     "reason": "原料已出库但加工来源尚未结清：需核对已领、已完成、已交接及在制数量；只能沿原领料证据接续，不能新建领料再次扣原料。"})
    orders = OutsourcingOrder.objects.filter(stock_mode="LEGACY").exclude(status__in=["COMPLETED", "CANCELLED"]).annotate(
        has_dispatch=Exists(OutsourcingDispatch.objects.filter(order_id=OuterRef("pk"))),
        has_handoff=Exists(MetalProcessingOriginalHandoff.objects.filter(original_order_id=OuterRef("pk"))),
    ).order_by("id").values("id", "order_number", "status", "has_dispatch", "has_handoff")
    for row in orders:
        if row["has_dispatch"] or row["has_handoff"]:
            add("OUTSOURCING", row, "order_number", "IN_TRANSIT_FROZEN_IDENTITY_REQUIRED",
                "已发出或交接：需核对未回数量、实际工艺、当时冻结实物属性和原料退回依据。缺少资料须补充可核实原凭证；不能用今天的 BOM 猜补。备注结清后仍可能补回货。")
        else:
            add("OUTSOURCING", row, "order_number", "UNDISPATCHED_PLAN_RECREATE",
                "尚未实际发出：可按原流程取消旧计划，经当前 BOM 和订单余量核验后重建公共外发单。")
    for row in MetalProcessingExternalOrder.objects.filter(stock_mode="LEGACY").exclude(status="COMPLETED").order_by("id").values(
            "id", "order_number", "status", "handoff_pieces", "returned_good_pieces"):
        dispatched = row["handoff_pieces"] > 0
        add("REWORK_OUTSOURCING", row, "order_number",
            "IN_TRANSIT_FROZEN_IDENTITY_REQUIRED" if dispatched else "REWORK_PLAN_REVIEW",
            "需沿原未喷塑退回、重加工及交接冻结资料核验接续；不能再次扣原材料，也不能凭当前 BOM 重建历史颜色和尺寸。")
    return {
        "schema_version": 1,
        "read_only": True,
        "public_flow_enabled": public_flow_enabled(),
        "scope": "旧未结单清单；不替代期初库存对账、BOM 缺值核验或正式切换授权。",
        "total": len(rows), "counts": dict(Counter(row["code"] for row in rows)), "documents": rows,
    }
