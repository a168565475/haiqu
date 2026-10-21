"""车间成功动作的事实快照；收件角色和文案统一由通知规则解析。"""
from django.utils import timezone

from .notification_services import register_business_event


WORKSHOP_EVENTS = {
    "MATERIAL_ISSUE_SUBMITTED", "WAGE_SCHEME_SUBMITTED", "WAGE_SCHEME_DECIDED",
    "WORK_REPORT_SAVED", "OUTSOURCING_ORDER_CREATED", "TUBE_OUTSOURCING_ORDER_CREATED",
}


def workshop_object(event_code, object_id):
    if event_code == "MATERIAL_ISSUE_SUBMITTED":
        from apps.material_issues.models import MaterialIssue
        return MaterialIssue.objects.filter(pk=object_id).first()
    if event_code in {"WAGE_SCHEME_SUBMITTED", "WAGE_SCHEME_DECIDED"}:
        from apps.workshop_reporting.models import WageScheme
        return WageScheme.objects.filter(pk=object_id).first()
    if event_code == "WORK_REPORT_SAVED":
        from apps.workshop_reporting.models import WorkReport
        return WorkReport.objects.filter(pk=object_id).first()
    if event_code == "OUTSOURCING_ORDER_CREATED":
        from apps.outsourcing.models import OutsourcingOrder
        return OutsourcingOrder.objects.filter(pk=object_id).first()
    if event_code == "TUBE_OUTSOURCING_ORDER_CREATED":
        from apps.outsourcing.models import TubeOutsourcingOrder
        return TubeOutsourcingOrder.objects.filter(pk=object_id).first()
    return None


def current_workshop_object(event_code, object_id, object_version=None):
    if event_code == "TUBE_OUTSOURCING_ORDER_CREATED":
        from django.conf import settings
        from apps.inventory.public_stock_mode import public_flow_enabled
        if not getattr(settings, "TUBE_OUTSOURCING_ENABLED", False) or not public_flow_enabled():
            return None
    obj = workshop_object(event_code, object_id)
    if obj is None:
        return None
    version = obj.revision if event_code in {"WAGE_SCHEME_SUBMITTED", "WAGE_SCHEME_DECIDED", "WORK_REPORT_SAVED"} else obj.version
    if object_version is not None and str(version) != str(object_version):
        return None
    expected = {
        "MATERIAL_ISSUE_SUBMITTED": {"PENDING_REVIEW"},
        "WAGE_SCHEME_SUBMITTED": {"PENDING_APPROVAL"},
        "WAGE_SCHEME_DECIDED": {"APPROVED", "RETURNED"},
        "OUTSOURCING_ORDER_CREATED": {"PENDING_DISPATCH"},
        "TUBE_OUTSOURCING_ORDER_CREATED": {"PENDING_DISPATCH"},
    }
    if event_code in expected and obj.status not in expected[event_code]:
        return None
    if event_code == "MATERIAL_ISSUE_SUBMITTED":
        task = obj.production_task
    elif event_code == "OUTSOURCING_ORDER_CREATED":
        task = obj.schedule.production_task
    else:
        task = obj.product_line.production_task
    return obj if task is not None and task.archived_at is None else None


def _register(code, obj, actor, document_no, version, **facts):
    context = {
        "document_no": document_no, "operator": actor.display_name,
        "occurred_at": timezone.localtime().isoformat(timespec="seconds"), **facts,
    }
    return register_business_event(
        event_code=code, idempotency_key=f"{code}:{obj.pk}:{version}",
        object_type=obj._meta.label, object_id=obj.pk, object_version=version, context=context,
    )


def issue_submitted(issue, actor):
    return _register("MATERIAL_ISSUE_SUBMITTED", issue, actor, issue.issue_number, issue.version,
        workshop_id=str(issue.workshop_id), workshop_name=issue.workshop.name,
        product_name=issue.product_line.product_name_snapshot, status=issue.get_status_display())


def scheme_changed(scheme, actor, *, submitted=False):
    return _register("WAGE_SCHEME_SUBMITTED" if submitted else "WAGE_SCHEME_DECIDED",
        scheme, actor, scheme.scheme_number, scheme.revision,
        workshop_id=str(scheme.workshop_id), workshop_name=scheme.workshop.name,
        product_name=scheme.product_name_snapshot, status=scheme.get_status_display())


def report_saved(report, actor):
    return _register("WORK_REPORT_SAVED", report, actor, report.report_number, report.revision,
        workshop_id=str(report.workshop_id), workshop_name=report.workshop.name,
        product_name=report.product_name_snapshot, status="已保存")


def outsourcing_created(order, actor, *, tube=False):
    code = "TUBE_OUTSOURCING_ORDER_CREATED" if tube else "OUTSOURCING_ORDER_CREATED"
    facts = {"status": "待外发" if tube else order.get_status_display()}
    if tube:
        from apps.outsourcing.source_access import DIRECT_WORKSHOPS
        from apps.workshop_config.models import Workshop
        name = DIRECT_WORKSHOPS.get(order.source_kind)
        workshop = Workshop.objects.filter(name=name, status="ACTIVE").first() if name else None
        facts.update(source_kind=order.source_kind, source_name=order.get_source_kind_display(),
                     product_name=order.product_line.product_name_snapshot)
        if workshop:
            facts.update(workshop_id=str(workshop.pk), workshop_name=workshop.name)
    return _register(code, order, actor, order.order_number, order.version, **facts)
