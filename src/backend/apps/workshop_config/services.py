from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.organizations.models import Employee
from apps.organizations.selectors import active_department_employees

from .models import Craft, Operation, RecordStatus, Workshop


class ActiveChildrenConflict(Conflict):
    api_error_code = "ACTIVE_CHILDREN_EXIST"

    def __init__(self, message, *, blockers):
        self.error_meta = {"blockers": blockers}
        super().__init__(message)


def _next_operation_number():
    while True:
        candidate = f"OP-{uuid4().hex[:20].upper()}"
        if not Operation.objects.filter(operation_number=candidate).exists():
            return candidate


def _snapshot(instance):
    if isinstance(instance, Workshop):
        return {"name": instance.name, "status": instance.status}
    if isinstance(instance, Craft):
        return {
            "craft_type": instance.craft_type,
            "workshop_id": str(instance.workshop_id) if instance.workshop_id else None,
            "name": instance.name,
            "plan_category": instance.plan_category,
            "outsourcing_code": instance.outsourcing_code,
            "status": instance.status,
        }
    if isinstance(instance, Operation):
        return {
            "operation_number": instance.operation_number,
            "product_name": instance.product_name,
            "craft_id": str(instance.craft_id),
            "name": instance.name,
            "status": instance.status,
        }
    raise TypeError("不支持的车间配置类型。")


def _object_type(instance):
    return {
        Workshop: "WORKSHOP",
        Craft: "WORKSHOP_CRAFT",
        Operation: "WORKSHOP_OPERATION",
    }[type(instance)]


@transaction.atomic
def create_config(*, model_class, validated_data, actor_employee, request=None):
    if model_class is Operation and not validated_data.get("operation_number"):
        validated_data = {**validated_data, "operation_number": _next_operation_number()}
    instance = model_class(
        created_by_employee=actor_employee,
        updated_by_employee=actor_employee,
        **validated_data,
    )
    instance.full_clean()
    instance.save()
    write_audit_log(
        object_type=_object_type(instance),
        object_id=instance.pk,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=_snapshot(instance),
        request=request,
    )
    return instance


def _enforce_disable_gate(instance, validated_data):
    next_status = validated_data.get("status", instance.status)
    if instance.status == next_status or next_status != RecordStatus.INACTIVE:
        return
    if isinstance(instance, Workshop):
        active_employees = instance.production_employees.filter(workshop_status="ACTIVE").count()
        active_crafts = instance.crafts.filter(status=RecordStatus.ACTIVE).count()
        blockers = []
        if active_employees:
            blockers.append({"resource": "employees", "count": active_employees})
        if active_crafts:
            blockers.append({"resource": "crafts", "count": active_crafts})
        if blockers:
            raise ActiveChildrenConflict("车间仍有启用的员工或工艺，不能停用。", blockers=blockers)
    if isinstance(instance, Craft):
        active_operations = instance.operations.filter(status=RecordStatus.ACTIVE).count()
        if active_operations:
            raise ActiveChildrenConflict(
                "工艺仍有启用的工序，不能停用。",
                blockers=[{"resource": "operations", "count": active_operations}],
            )


@transaction.atomic
def update_config(*, model_class, instance_id, validated_data, actor_employee, request):
    instance = model_class.objects.select_for_update().get(pk=instance_id)
    require_matching_etag(request, instance)
    _enforce_disable_gate(instance, validated_data)
    before_data = _snapshot(instance)
    for field_name, value in validated_data.items():
        setattr(instance, field_name, value)
    instance.updated_by_employee = actor_employee
    instance.full_clean()
    instance.save()
    write_audit_log(
        object_type=_object_type(instance),
        object_id=instance.pk,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=_snapshot(instance),
        request=request,
    )
    return instance


@transaction.atomic
def update_employee_workshop(*, instance_id, validated_data, actor_employee, request):
    instance = Employee.objects.select_for_update().get(pk=instance_id)
    require_matching_etag(request, instance)
    if not active_department_employees("DEPT_PRODUCTION").filter(pk=instance.pk).exists():
        raise Conflict("员工已不属于生产部，请刷新列表。")
    fields = ("workshop_id", "workshop_position", "workshop_is_supervisor", "workshop_status")
    before = {key: str(getattr(instance, key)) if key == "workshop_id" and getattr(instance, key) else getattr(instance, key) for key in fields}
    for key, value in validated_data.items():
        if key not in {"workshop", "workshop_position", "workshop_is_supervisor", "workshop_status"}:
            raise ValidationError({key: "此处只能调整车间专用字段。"})
        setattr(instance, key, value)
    if instance.workshop_id:
        if instance.workshop.status != RecordStatus.ACTIVE or not instance.workshop_position.strip():
            raise ValidationError({"workshop": "请选择启用的车间并填写岗位。"})
    elif instance.workshop_position or instance.workshop_is_supervisor:
        raise ValidationError({"workshop": "未安排车间时不能填写岗位或主管。"})
    instance.full_clean()
    instance.save(update_fields=["workshop", "workshop_position", "workshop_is_supervisor", "workshop_status", "updated_at"])
    after = {key: str(getattr(instance, key)) if key == "workshop_id" and getattr(instance, key) else getattr(instance, key) for key in fields}
    write_audit_log(object_type="EMPLOYEE_WORKSHOP", object_id=instance.pk, action="UPDATED",
                    actor_employee=actor_employee, before_data=before, after_data=after, request=request)
    return instance
