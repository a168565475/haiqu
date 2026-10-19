from decimal import Decimal, ROUND_HALF_UP, localcontext

from django.utils import timezone
from rest_framework import serializers

from ..models import WageSchemeLineStatus, WageSchemeStatus, WorkCountingMode


class WageSchemeLineWriteSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    work_item_id = serializers.UUIDField(required=False)
    craft_id = serializers.UUIDField()
    operation_id = serializers.UUIDField()
    bom_line_id = serializers.UUIDField(required=False, allow_null=True)
    display_name = serializers.CharField(max_length=200, trim_whitespace=True)
    counting_mode = serializers.ChoiceField(
        choices=WorkCountingMode.choices, required=False, default=WorkCountingMode.ORDER
    )
    production_description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    previous_price = serializers.DecimalField(max_digits=18, decimal_places=4, required=False, allow_null=True, min_value=Decimal("0"))
    revised_price = serializers.DecimalField(max_digits=18, decimal_places=4, required=False, allow_null=True, min_value=Decimal("0"))
    declared_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    status = serializers.ChoiceField(choices=WageSchemeLineStatus.choices, required=False, default=WageSchemeLineStatus.ACTIVE)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)


class WageSchemeWriteSerializer(serializers.Serializer):
    product_line_id = serializers.UUIDField(required=False)
    workshop_id = serializers.UUIDField(required=False)
    schedule_product_id = serializers.UUIDField(required=False, allow_null=True)
    craft_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, required=False)
    operation_product_name = serializers.CharField(max_length=200, trim_whitespace=True, required=False)
    remark = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    history_source_scheme_id = serializers.UUIDField(required=False, allow_null=True)
    lines = WageSchemeLineWriteSerializer(many=True, allow_empty=False, required=False)

    def validate(self, attrs):
        if self.instance is None:
            for field in ("product_line_id", "workshop_id", "craft_ids", "lines"):
                if field not in attrs:
                    raise serializers.ValidationError({field: "此字段为必填项。"})
        return attrs


class WageSchemeApprovalSerializer(serializers.Serializer):
    effective_from = serializers.DateField(required=False)
    effective_to = serializers.DateField(required=False, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attrs):
        effective_from = attrs.get("effective_from") or timezone.localdate()
        if attrs.get("effective_to") and attrs["effective_to"] < effective_from:
            raise serializers.ValidationError({"effective_to": "结束日期不能早于开始日期。"})
        return attrs


class CommentSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class WorkReportLineWriteSerializer(serializers.Serializer):
    scheme_line_id = serializers.UUIDField()
    workshop_employee_id = serializers.UUIDField()
    production_line = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=3)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))

    def validate_quantity(self, value):
        if value != value.to_integral_value():
            raise serializers.ValidationError("完成次数必须是正整数。")
        return value


class WorkReportWriteSerializer(serializers.Serializer):
    client_request_id = serializers.UUIDField()
    production_date = serializers.DateField()
    schedule_product_id = serializers.UUIDField()
    scheme_id = serializers.UUIDField()
    scheme_revision = serializers.IntegerField(min_value=1)
    confirm_plan_completion = serializers.BooleanField(required=False, default=False)
    lines = WorkReportLineWriteSerializer(many=True, allow_empty=False)


class WorkReportUpdateSerializer(serializers.Serializer):
    production_date = serializers.DateField()
    schedule_product_id = serializers.UUIDField()
    scheme_id = serializers.UUIDField()
    scheme_revision = serializers.IntegerField(min_value=1)
    confirm_plan_completion = serializers.BooleanField(required=False, default=False)
    lines = WorkReportLineWriteSerializer(many=True, allow_empty=False)


class WorkReportDeleteSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, allow_blank=False, trim_whitespace=True)


def _estimated_line_amount(line):
    if line.status != WageSchemeLineStatus.ACTIVE or line.required_quantity_snapshot is None:
        return None
    # 数量和单价的合法位数相乘可能超过 Decimal 默认的 28 位精度。
    with localcontext() as context:
        context.prec = 48
        return str((line.required_quantity_snapshot * line.declared_price).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP,
        ))


def wage_scheme_data(scheme, *, detail=True, line_metrics=None):
    line_metrics = line_metrics or {}
    lines = []
    events = []
    if detail:
        lines = [
            {
                "id": str(line.pk),
                "line_number": line.line_number,
                "work_item_id": str(line.work_item_id),
                "craft_id": str(line.work_item.craft_id),
                "operation_id": str(line.work_item.operation_id),
                "display_name": line.display_name_snapshot,
                "production_description": line.production_description,
                "craft_name": line.craft_name_snapshot,
                "operation_name": line.operation_name_snapshot,
                "operation_number": line.operation_number_snapshot,
                "unit_name": line.unit_name_snapshot,
                "bom_component_identity": (
                    str(line.bom_component_identity_snapshot)
                    if line.bom_component_identity_snapshot else None
                ),
                "counting_mode": line.counting_mode,
                "counting_mode_display": line.get_counting_mode_display(),
                "order_quantity": line.order_quantity_snapshot,
                "required_quantity": (
                    str(line.required_quantity_snapshot)
                    if line.required_quantity_snapshot is not None else None
                ),
                "completed_quantity": line_metrics.get(line.work_item_id, {}).get("completed_quantity"),
                "completed_amount": line_metrics.get(line.work_item_id, {}).get("completed_amount"),
                "estimated_amount": _estimated_line_amount(line),
                "previous_price": str(line.previous_price) if line.previous_price is not None else None,
                "revised_price": str(line.revised_price) if line.revised_price is not None else None,
                "declared_price": str(line.declared_price),
                "status": line.status,
                "note": line.note,
            }
            for line in scheme.lines.all()
        ]
        events = [
            {
                "id": str(event.pk), "action": event.action,
                "action_display": event.get_action_display(), "scheme_revision": event.scheme_revision,
                "actor": event.actor_employee.display_name, "comment": event.comment,
                "created_at": event.created_at,
            }
            for event in scheme.events.all()
        ]
    task = scheme.product_line.production_task
    return {
        "id": str(scheme.pk),
        "scheme_number": scheme.scheme_number,
        "status": scheme.status,
        "status_display": scheme.get_status_display(),
        "version": scheme.version,
        "revision": scheme.revision,
        "can_create_change": (
            scheme.status == WageSchemeStatus.APPROVED and not bool(list(scheme.change_versions.all()))
        ),
        "parent_scheme": ({
            "id": str(scheme.parent_scheme_id),
            "scheme_number": scheme.parent_scheme.scheme_number,
            "version": scheme.parent_scheme.version,
            "effective_from": scheme.parent_scheme.effective_from,
            "effective_to": scheme.parent_scheme.effective_to,
        } if scheme.parent_scheme_id else None),
        "product_line_id": str(scheme.product_line_id),
        "schedule_product_id": str(scheme.schedule_product_id) if scheme.schedule_product_id else None,
        "production_task": {"id": str(task.pk), "task_number": task.task_number, "order_number": task.order_number},
        "product": {
            "name": scheme.product_name_snapshot,
            "number": scheme.product_number_snapshot,
            "specification": scheme.product_specification_snapshot,
        },
        "workshop": {"id": str(scheme.workshop_id), "name": scheme.workshop.name},
        "scope_craft": {
            "id": str(scheme.scope_craft_id), "name": scheme.scope_craft.name,
            "plan_category": scheme.scope_craft.plan_category,
        },
        "crafts": [{"id": str(item.craft_id), "name": item.craft.name} for item in scheme.scheme_crafts.all()],
        "operation_product_name": scheme.operation_product_name_snapshot,
        "effective_from": scheme.effective_from,
        "effective_to": scheme.effective_to,
        "remark": scheme.remark,
        "line_count": len(lines) if detail else scheme.lines.count(),
        "declared_total": str(sum((line.declared_price for line in scheme.lines.all() if line.status == WageSchemeLineStatus.ACTIVE), Decimal("0"))),
        "lines": lines,
        "events": events,
        "approved_by": scheme.approved_by_employee.display_name if scheme.approved_by_employee_id else None,
        "approved_at": scheme.approved_at,
        "created_by_id": str(scheme.created_by_employee_id),
        "created_by": scheme.created_by_employee.display_name,
        "created_at": scheme.created_at,
        "updated_at": scheme.updated_at,
    }


def work_report_data(report, *, detail=True, line_metrics=None, request=None):
    from apps.core.api.concurrency import etag_for_instance
    from ..report_history import can_delete_report
    line_metrics = line_metrics or {}
    lines = []
    if detail:
        lines = [
            {
                "id": str(line.pk), "line_number": line.line_number,
                "scheme_line_id": str(line.scheme_line_id), "work_item_id": str(line.work_item_id),
                "workshop_employee_id": str(line.workshop_employee_id),
                "employee_name": line.employee_name_snapshot, "production_line": line.production_line,
                "display_name": line.display_name_snapshot, "craft_name": line.craft_name_snapshot,
                "operation_name": line.operation_name_snapshot, "unit_name": line.unit_name_snapshot,
                "quantity": str(line.quantity), "order_quantity_snapshot": line.order_quantity_snapshot,
                "cumulative_quantity": line_metrics.get(line.pk, {}).get("cumulative_quantity"),
                "required_quantity": (
                    line_metrics.get(line.pk, {}).get("required_quantity")
                    or (
                        str(line.required_quantity_snapshot)
                        if line.required_quantity_snapshot is not None else None
                    )
                ),
                "unit_price": str(line.unit_price_snapshot), "amount": str(line.amount),
            }
            for line in report.lines.all()
        ]
    return {
        "id": str(report.pk), "report_number": report.report_number, "production_date": report.production_date,
        "etag": etag_for_instance(report), "can_delete": can_delete_report(request, report),
        "production_task": {
            "id": str(report.product_line.production_task_id),
            "task_number": report.task_number_snapshot,
            "order_number": report.order_number_snapshot,
        },
        "product": {"name": report.product_name_snapshot, "number": report.product_number_snapshot},
        "product_line_id": str(report.product_line_id), "schedule_product_id": str(report.schedule_product_id),
        "workshop": {"id": str(report.workshop_id), "name": report.workshop.name},
        "scope_craft": {
            "id": str(report.scheme.scope_craft_id), "name": report.scheme.scope_craft.name,
            "plan_category": report.scheme.scope_craft.plan_category,
        },
        "scheme_id": str(report.scheme_id), "scheme_version": report.scheme_version_snapshot,
        "revision": report.revision,
        "recorder": report.recorder_name_snapshot, "total_amount": str(report.total_amount),
        "completed_plan": report.completed_plan,
        "updated_by": report.updated_by_employee.display_name,
        "line_count": len(lines) if detail else report.lines.count(), "lines": lines,
        "created_at": report.created_at, "updated_at": report.updated_at,
    }
