from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.organizations.models import Employee

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
            "employee_id": str(instance.employee_id) if instance.employee_id else None,
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


def _employee_config_data(data, instance=None):
    data = dict(data)
    if "name" in data:
        raise ValidationError({"name": "姓名来自统一员工档案，不能在车间配置中修改。"})
    current_id = instance.employee_id if instance else None
    selected = data.get("employee")
    employee_id = current_id
    if "employee" in data:
        employee_id = selected.pk if selected is not None else None
    if current_id and employee_id != current_id:
        raise ValidationError({"employee": "已关联的员工不能更换或解除关联。"})
    if employee_id is None:
        if instance is None:
            raise ValidationError({"employee": "请选择统一员工档案。"})
        return data
    # 更新先锁车间记录，再锁统一员工；重新读取状态，避免使用校验阶段的旧对象。
    employee = Employee.objects.select_for_update(no_key=True).filter(pk=employee_id).first()
    if employee is None:
        raise ValidationError({"employee": "统一员工档案不存在。"})
    status = data.get("status", instance.status if instance else WorkshopEmployeeStatus.ACTIVE)
    if not current_id or status == WorkshopEmployeeStatus.ACTIVE:
        if employee.status != "ACTIVE" or employee.archived_at is not None:
            raise ValidationError({"employee": "只能关联或启用在职且未归档的员工。"})
    data["employee"] = employee
    if instance is None:
        if len(employee.display_name) > 100:
            raise ValidationError({"employee": "员工姓名超过 100 字符，当前车间及报工姓名字段无法保存。"})
        data["name"] = employee.display_name
    return data


@transaction.atomic
def create_config(*, model_class, validated_data, actor_employee, request=None):
    if model_class is WorkshopEmployee:
        validated_data = _employee_config_data(validated_data)
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
    if model_class is WorkshopEmployee:
        validated_data = _employee_config_data(validated_data, instance)
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
