from django.db import transaction

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log

from .models import Craft, Operation, RecordStatus, Workshop, WorkshopEmployee, WorkshopEmployeeStatus


class ActiveChildrenConflict(Conflict):
    api_error_code = "ACTIVE_CHILDREN_EXIST"

    def __init__(self, message, *, blockers):
        self.error_meta = {"blockers": blockers}
        super().__init__(message)


def _snapshot(instance):
    if isinstance(instance, Workshop):
        return {"name": instance.name, "status": instance.status}
    if isinstance(instance, WorkshopEmployee):
        return {
            "workshop_id": str(instance.workshop_id),
            "position": instance.position,
            "name": instance.name,
            "is_supervisor": instance.is_supervisor,
            "status": instance.status,
        }
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
        WorkshopEmployee: "WORKSHOP_EMPLOYEE",
        Craft: "WORKSHOP_CRAFT",
        Operation: "WORKSHOP_OPERATION",
    }[type(instance)]


@transaction.atomic
def create_config(*, model_class, validated_data, actor_employee, request=None):
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
        active_employees = instance.employees.filter(status=WorkshopEmployeeStatus.ACTIVE).count()
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
