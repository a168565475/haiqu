import json
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from apps.audit.models import AuditLog


def _json_value(value):
    return json.loads(json.dumps(value or {}, cls=DjangoJSONEncoder))


def _request_id(request):
    if request is None:
        return None
    try:
        return uuid.UUID(request.request_id)
    except (AttributeError, TypeError, ValueError):
        return None


def write_audit_log(
    *,
    object_type,
    object_id,
    action,
    actor_employee=None,
    before_data=None,
    after_data=None,
    context_type="",
    context_id=None,
    request=None,
):
    return AuditLog.objects.create(
        actor_employee=actor_employee,
        actor_employee_code_snapshot=getattr(actor_employee, "employee_code", ""),
        actor_name_snapshot=getattr(actor_employee, "display_name", ""),
        object_type=object_type,
        object_id=object_id,
        context_type=context_type,
        context_id=context_id,
        action=action,
        before_data=_json_value(before_data),
        after_data=_json_value(after_data),
        request_id=_request_id(request),
        ip_address=request.META.get("REMOTE_ADDR") if request else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:500] if request else ""),
        occurred_at=timezone.now(),
    )
