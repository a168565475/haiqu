"""金工加工与补加工的不可变业务凭证，补充通用审计没有覆盖的动作。"""
from apps.access_control.module_policy import has_permission
from apps.material_issues import models
from apps.material_issues.processing_selectors import processing_lines
from .detail_related import _read_request


def metal_events(request, task_id, product_ids, external_orders):
    from .timeline import event_row
    permission = "material_issues.view_metalprocessingsource"
    if not has_permission(request, permission):
        return []
    lines = processing_lines(_read_request(request, permission), permission=permission).filter(
        issue__production_task_id=task_id, issue__product_line_id__in=product_ids)
    sources = models.MetalProcessingSource.objects.filter(issue_line__in=lines)
    rows = []
    for model, lookup, actor_field, action, label in (
        (models.MetalProcessingCompletion, "source__in", "actor_employee", "COMPLETED", "金工加工"),
        (models.MetalProcessingClosure, "source__in", "actor_employee", "CLOSED", "金工加工"),
        (models.MetalProcessingRework, "source__in", "actor_employee", "COMPLETED", "金工返工"),
        (models.MetalProcessingExternalHandoff, "order__in", "actor_employee", "DISPATCH_CONFIRMED", "补加工外发"),
        (models.MetalProcessingExternalGoodReturn, "order__in", "received_by_employee", "RETURN_COMPLETED", "补加工回货"),
        (models.MetalProcessingExternalClosure, "order__in", "actor_employee", "CLOSED", "补加工外发"),
    ):
        scope = external_orders if lookup == "order__in" else sources
        related = [actor_field, "order"] if lookup == "order__in" else [actor_field]
        for record in model.objects.filter(**{lookup: scope}).select_related(*related):
            number = getattr(record, "return_number", "")
            path = None
            if getattr(record, "order_id", None):
                path = f"/workshop/outsourcing/rework/{record.order_id}"
                number = record.order.order_number
            rows.append(event_row(identity=f"metal:{model.__name__}:{record.pk}", kind="METAL_PROCESSING",
                label=label, action=action, actor=getattr(record, actor_field).display_name,
                at=record.created_at, number=number, path=path, after={"remark": getattr(record, "remark", "")}))
    for order in external_orders.select_related("created_by_employee"):
        rows.append(event_row(identity=f"metal-order:{order.pk}", kind="METAL_PROCESSING", label="补加工外发单",
            action="CREATED", actor=order.created_by_employee.display_name, at=order.created_at,
            number=order.order_number, path=f"/workshop/outsourcing/rework/{order.pk}"))
    return rows
