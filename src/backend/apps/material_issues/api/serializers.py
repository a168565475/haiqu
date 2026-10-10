from decimal import Decimal

from rest_framework import serializers

from ..material_flow import line_stock, line_flow_data
from ..models import MaterialIssue, MaterialIssueAction, MaterialIssueStatus


QUANTITY_SNAPSHOT_FIELDS = (
    "required_quantity",
    "internal_issued_quantity",
    "outsourcing_issued_quantity",
    "order_remaining",
    "available_stock",
    "max_issue_quantity",
)


def _semi_material(line, source=None):
    public_identity = line.conversion_snapshot.get("public_identity", {})
    identity_snapshot = public_identity.get("identity_snapshot", {}) if isinstance(public_identity, dict) else {}
    material = identity_snapshot.get("material") if isinstance(identity_snapshot, dict) else None
    if material:
        return material
    source_identity = getattr(source, "identity_snapshot", {})
    if isinstance(source_identity, dict) and source_identity.get("material"):
        return source_identity["material"]
    bom_line = getattr(source, "bom_line", None)
    return getattr(bom_line, "material", "") or ""


class MaterialIssueBatchWriteSerializer(serializers.Serializer):
    inbound_line_id = serializers.UUIDField()
    requested_pieces = serializers.DecimalField(max_digits=14, decimal_places=0, min_value=1)


class MaterialIssueLineWriteSerializer(serializers.Serializer):
    requirement_id = serializers.UUIDField()
    batch_allocations = MaterialIssueBatchWriteSerializer(many=True, required=False, max_length=1000)
    requested_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))


class MaterialIssueWriteSerializer(serializers.Serializer):
    client_request_id = serializers.UUIDField(required=False)
    schedule_product_id = serializers.UUIDField(required=False)
    plan_category = serializers.CharField(required=False, max_length=20)
    production_task_id = serializers.UUIDField(required=False, allow_null=True)
    product_line_id = serializers.UUIDField(required=False, allow_null=True)
    workshop_id = serializers.UUIDField(required=False, allow_null=True)
    recipient_workshop_employee_id = serializers.UUIDField(required=False, allow_null=True)
    issue_at = serializers.DateTimeField(required=False, allow_null=True)
    remark = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    lines = MaterialIssueLineWriteSerializer(many=True, required=False)

    def validate(self, attrs):
        if self.instance is None and "client_request_id" not in attrs:
            raise serializers.ValidationError({"client_request_id": "创建领料单必须提供提交标识。"})
        if self.instance is None and "schedule_product_id" not in attrs:
            raise serializers.ValidationError({"schedule_product_id": "生产领料必须从作业计划发起。"})
        if self.instance is None and "plan_category" not in attrs:
            raise serializers.ValidationError({"plan_category": "生产领料必须携带作业计划类型。"})
        return attrs


class MaterialIssueReturnSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=2, max_length=1000, trim_whitespace=True)


class MaterialIssueConfirmSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()


class MaterialIssueReadSerializer(serializers.Serializer):
    def to_representation(self, issue: MaterialIssue):
        include_detail = self.context.get("include_detail", True)
        lines = []
        public_quantity_context = None
        issued_snapshots = {}
        if include_detail and issue.status == MaterialIssueStatus.ISSUED:
            issued_event = next(
                (event for event in issue.audit_events.all() if event.action == MaterialIssueAction.ISSUED),
                None,
            )
            if issued_event:
                issued_snapshots = {
                    item["line_id"]: item
                    for item in issued_event.snapshot.get("issued_line_snapshots", [])
                    if item.get("line_id")
                }
        if include_detail:
            # 在已预加载的结果上排序，避免重新查询后丢失各明细的关联缓存。
            for line in sorted(issue.lines.all(), key=lambda item: (item.line_number, item.pk)):
                issued_snapshot = issued_snapshots.get(str(line.pk), {})
                if issue.stock_mode == "PUBLIC_V2":
                    from ..public_issue_services import public_issue_quantity_context, public_line_flow_data, public_line_quantities
                    if all(field in issued_snapshot for field in QUANTITY_SNAPSHOT_FIELDS):
                        quantities = {field: issued_snapshot[field] for field in QUANTITY_SNAPSHOT_FIELDS}
                        quantities["pending_issue_quantity"] = issued_snapshot.get("pending_issue_quantity", "0")
                    else:
                        if public_quantity_context is None:
                            public_quantity_context = public_issue_quantity_context(issue, exclude_issue_id=issue.pk,
                                                                                    lines=list(issue.lines.all()))
                        quantities = public_line_quantities(line, context=public_quantity_context)
                    semi_requirement = line.semi_requirement if line.semi_requirement_id else None
                    flow = public_line_flow_data(line)
                    lines.append({
                        **flow, **quantities,
                        "id": str(line.pk), "line_number": line.line_number,
                        "stock_mode": "PUBLIC_V2",
                        "requirement_id": str(line.semi_requirement_id or line.requirement_id),
                        "line_type": line.line_type, "section_code": line.section_code_snapshot,
                        "raw_material_id": str(line.raw_material_id) if line.raw_material_id else None,
                        "material_number": line.material_number_snapshot,
                        "material_name": line.material_name_snapshot,
                        "material": _semi_material(line, semi_requirement) if line.line_type == "SEMI" else "",
                         "bom_attributes": line.conversion_snapshot.get("bom_attributes", []),
                        "specification": line.specification_snapshot, "color": line.color_snapshot,
                        "unit": line.unit_snapshot, "requested_quantity": str(line.requested_quantity),
                        "issued_quantity": str(line.issued_quantity) if line.issued_quantity is not None else None,
                        "completed_craft": line.conversion_snapshot.get("completed_craft", semi_requirement.completed_craft.name if semi_requirement else ""),
                        "warehouse_zone": line.conversion_snapshot.get("warehouse_zone", ""),
                        "quality": "AVAILABLE",
                        **{field: issued_snapshot[field] for field in ("stock_before", "stock_after") if field in issued_snapshot},
                    })
                    continue
                if line.line_type == "SEMI":
                    balance = line.semi_finished_balance
                    stock = balance.quantity
                    lines.append(
                        {
                            **line_flow_data(line),
                            "id": str(line.pk),
                            "line_number": line.line_number,
                            "requirement_id": str(balance.pk),
                            "line_type": line.line_type,
                            "section_code": line.section_code_snapshot,
                            "raw_material_id": None,
                            "semi_finished_balance_id": str(balance.pk),
                            "material_number": line.material_number_snapshot,
                            "material_name": line.material_name_snapshot,
                            "material": _semi_material(line, balance),
                             "bom_attributes": line.conversion_snapshot.get("bom_attributes", []),
                            "specification": line.specification_snapshot,
                            "color": line.color_snapshot,
                            "unit": line.unit_snapshot,
                            "required_quantity": issued_snapshot.get("required_quantity", str(stock + (line.issued_quantity or Decimal("0")))),
                            "internal_issued_quantity": issued_snapshot.get("internal_issued_quantity", str(line.issued_quantity or Decimal("0"))),
                            "outsourcing_issued_quantity": issued_snapshot.get("outsourcing_issued_quantity", "0"),
                            "order_remaining": issued_snapshot.get("order_remaining", str(stock)),
                            "available_stock": issued_snapshot.get("available_stock", str(stock)),
                            "max_issue_quantity": issued_snapshot.get("max_issue_quantity", str(stock)),
                            "requested_quantity": str(line.requested_quantity),
                            "issued_quantity": str(line.issued_quantity) if line.issued_quantity is not None else None,
                            "completed_craft": line.conversion_snapshot.get("completed_craft", balance.completed_craft.name),
                            "warehouse_zone": line.conversion_snapshot.get("warehouse_zone", f"{balance.zone.warehouse.warehouse_name} / {balance.zone.zone_name}"),
                            "quality": balance.quality,
                        }
                    )
                    continue
                if all(field in issued_snapshot for field in QUANTITY_SNAPSHOT_FIELDS):
                    quantities = {field: issued_snapshot[field] for field in QUANTITY_SNAPSHOT_FIELDS}
                else:
                    # 旧单缺快照时保留逐字段回退；完整已出库快照不再扫描当前库存。
                    requirement = line.requirement
                    remaining = (
                        requirement.required_quantity
                        - requirement.internal_issued_quantity
                        - requirement.outsourcing_issued_quantity
                    )
                    stock = line_stock(line)
                    quantities = {
                        "required_quantity": issued_snapshot.get("required_quantity", str(requirement.required_quantity)),
                        "internal_issued_quantity": issued_snapshot.get("internal_issued_quantity", str(requirement.internal_issued_quantity)),
                        "outsourcing_issued_quantity": issued_snapshot.get("outsourcing_issued_quantity", str(requirement.outsourcing_issued_quantity)),
                        "order_remaining": issued_snapshot.get("order_remaining", str(max(remaining, Decimal("0")))),
                        "available_stock": issued_snapshot.get("available_stock", str(stock)),
                        "max_issue_quantity": issued_snapshot.get("max_issue_quantity", str(max(min(remaining, stock), Decimal("0")))),
                    }
                lines.append(
                    {
                        **line_flow_data(line),
                        "id": str(line.pk),
                        "line_number": line.line_number,
                        "requirement_id": str(line.requirement_id),
                        "line_type": line.line_type,
                        "section_code": line.section_code_snapshot,
                        "raw_material_id": str(line.raw_material_id),
                        "material_number": line.material_number_snapshot,
                        "material_name": line.material_name_snapshot,
                        "bom_attributes": line.conversion_snapshot.get("bom_attributes", []),
                        "specification": line.specification_snapshot,
                        "color": line.color_snapshot,
                        "unit": line.unit_snapshot,
                        **quantities,
                        "requested_quantity": str(line.requested_quantity),
                        "issued_quantity": str(line.issued_quantity) if line.issued_quantity is not None else None,
                    }
                )
        events = []
        if include_detail:
            events = [
                {
                    "id": str(event.pk),
                    "action": event.action,
                    "action_display": event.get_action_display(),
                    "issue_version": event.issue_version,
                    "actor": {"id": str(event.actor_employee_id), "name": event.actor_employee.display_name},
                    "reason": event.reason,
                    "created_at": event.created_at,
                }
                for event in sorted(issue.audit_events.all(), key=lambda item: (item.created_at, item.pk))
            ]
        task = issue.production_task
        product = issue.product_line
        return {
            "id": str(issue.pk),
            "stock_mode": issue.stock_mode,
            "issue_number": issue.issue_number,
            "status": issue.status,
            "status_display": issue.get_status_display(),
            "version": issue.version,
            "production_task": (
                {
                    "id": str(task.pk),
                    "task_number": task.task_number,
                    "order_number": task.order_number,
                    "customer_name": task.customer_account.account_name,
                }
                if task
                else None
            ),
            "product": (
                {
                    "id": str(product.pk),
                    "product_number": product.product_number_snapshot,
                    "product_name": product.product_name_snapshot,
                    "specification": product.specification_snapshot,
                    "color": product.color_name_snapshot,
                    "quantity": str(product.quantity),
                    "unit": product.unit.unit_name,
                    "image_file_id": str(product.image_file_id) if product.image_file_id else None,
                }
                if product
                else None
            ),
            "workshop": (
                {"id": str(issue.workshop_id), "name": issue.workshop.name} if issue.workshop_id else None
            ),
            "recipient": (
                {
                    "id": str(issue.recipient_workshop_employee_id),
                    "name": issue.recipient_workshop_employee.name,
                }
                if issue.recipient_workshop_employee_id
                else None
            ),
            "issue_at": issue.issue_at,
            "remark": issue.remark,
            "source_revision_hash": issue.source_revision_hash,
            "line_count": len(lines) if include_detail else issue.lines.count(),
            "lines": lines,
            "audit_events": events,
            "created_by": {"id": str(issue.created_by_employee_id), "name": issue.created_by_employee.display_name},
            "submitted_at": issue.submitted_at,
            "issued_at": issue.issued_at,
            "issued_by": (
                {"id": str(issue.issued_by_employee_id), "name": issue.issued_by_employee.display_name}
                if issue.issued_by_employee_id
                else None
            ),
            "created_at": issue.created_at,
            "updated_at": issue.updated_at,
        }
