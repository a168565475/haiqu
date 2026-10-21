from rest_framework import serializers

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee

from ..constants import METAL_WORKSHOP_NAME
from ..models import Craft, CraftType, Operation, PlanCategory, RecordStatus, Workshop, WorkshopEmployee, WorkshopEmployeeStatus


def _normalized_text(value, label):
    normalized = value.strip()
    if not normalized:
        raise serializers.ValidationError(f"请输入{label}。")
    return normalized


class WorkshopSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    employee_count = serializers.IntegerField(read_only=True, default=0)
    active_employee_count = serializers.IntegerField(read_only=True, default=0)
    active_supervisor_count = serializers.IntegerField(read_only=True, default=0)
    craft_count = serializers.IntegerField(read_only=True, default=0)
    active_craft_count = serializers.IntegerField(read_only=True, default=0)
    operation_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Workshop
        fields = [
            "id", "name", "status", "status_display", "employee_count", "active_employee_count",
            "active_supervisor_count", "craft_count", "active_craft_count", "operation_count",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "name", "status", "status_display", "employee_count", "active_employee_count", "active_supervisor_count",
            "craft_count", "active_craft_count", "operation_count", "created_at", "updated_at",
        ]


class WorkshopEmployeeSerializer(serializers.ModelSerializer):
    workshop_name = serializers.CharField(source="workshop.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), required=False, allow_null=True)
    employee_code = serializers.CharField(source="employee.employee_code", read_only=True, default=None)
    employee_name = serializers.CharField(source="employee.display_name", read_only=True, default=None)
    employee_status = serializers.CharField(source="employee.status", read_only=True, default=None)
    employee_archived = serializers.SerializerMethodField()

    class Meta:
        model = WorkshopEmployee
        fields = [
            "id", "workshop", "workshop_name", "position", "name", "is_supervisor", "status",
            "employee", "employee_code", "employee_name", "employee_status", "employee_archived",
            "status_display", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "name", "workshop_name", "status_display", "created_at", "updated_at"]
        # 历史姓名只读；服务在事务内按最终身份校验两类条件唯一约束。
        validators = []

    def validate_position(self, value):
        return _normalized_text(value, "岗位")

    def get_employee_archived(self, obj) -> bool:
        return bool(obj.employee_id and obj.employee.archived_at is not None)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if "name" in self.initial_data:
            raise serializers.ValidationError({"name": "姓名来自统一员工档案，不能在车间配置中修改。"})
        if self.instance is None and attrs.get("employee") is None:
            raise serializers.ValidationError({"employee": "请选择统一员工档案。"})
        workshop = attrs.get("workshop", getattr(self.instance, "workshop", None))
        status = attrs.get("status", getattr(self.instance, "status", WorkshopEmployeeStatus.ACTIVE))
        if status == WorkshopEmployeeStatus.ACTIVE and workshop and workshop.status != RecordStatus.ACTIVE:
            raise serializers.ValidationError({"workshop": "在职员工不能关联已停用车间。"})
        return attrs


class WorkshopEmployeeOptionSerializer(serializers.ModelSerializer):
    etag = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = ["id", "employee_code", "display_name", "status", "etag"]
        read_only_fields = fields

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)


class CraftSerializer(serializers.ModelSerializer):
    craft_type_display = serializers.CharField(source="get_craft_type_display", read_only=True)
    workshop_name = serializers.CharField(source="workshop.name", read_only=True, allow_null=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    outsourcing_code_display = serializers.CharField(source="get_outsourcing_code_display", read_only=True, allow_null=True)
    operation_count = serializers.IntegerField(read_only=True, default=0)
    active_operation_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Craft
        fields = [
            "id", "craft_type", "craft_type_display", "workshop", "workshop_name", "name", "plan_category", "outsourcing_code", "outsourcing_code_display", "status",
            "status_display", "operation_count", "active_operation_count", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "craft_type_display", "workshop_name", "status_display", "operation_count",
            "active_operation_count", "outsourcing_code_display", "created_at", "updated_at",
        ]

    def validate_name(self, value):
        return _normalized_text(value, "工艺名称")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        craft_type = attrs.get("craft_type", getattr(self.instance, "craft_type", None))
        workshop = attrs.get("workshop", getattr(self.instance, "workshop", None))
        status = attrs.get("status", getattr(self.instance, "status", RecordStatus.ACTIVE))
        plan_category = attrs.get("plan_category", getattr(self.instance, "plan_category", None))
        outsourcing_code = attrs.get("outsourcing_code", getattr(self.instance, "outsourcing_code", None))
        if craft_type == CraftType.INTERNAL and workshop is None:
            raise serializers.ValidationError({"workshop": "厂内工艺必须选择车间。"})
        if craft_type == CraftType.EXTERNAL and workshop is not None:
            raise serializers.ValidationError({"workshop": "厂外工艺不能填写车间。"})
        if craft_type == CraftType.EXTERNAL and attrs.get("plan_category", getattr(self.instance, "plan_category", None)):
            raise serializers.ValidationError({"plan_category": "厂外工艺不能映射厂内计划。"})
        if plan_category == PlanCategory.METAL and (
            workshop is None or workshop.name != METAL_WORKSHOP_NAME
        ):
            raise serializers.ValidationError({"plan_category": "金工计划只能映射金工车间的工艺。"})
        if craft_type == CraftType.INTERNAL and outsourcing_code:
            raise serializers.ValidationError({"outsourcing_code": "厂内工艺不能绑定委外业务编码。"})
        if self.instance and (
            craft_type != self.instance.craft_type or outsourcing_code != self.instance.outsourcing_code
        ):
            if (self.instance.outsourcing_orders.exists() or self.instance.outsourcing_factories.exists()
                    or self.instance.tube_outsourcing_orders.exists()):
                raise serializers.ValidationError({"outsourcing_code": "已用于委外业务的工艺不能修改类型或委外编码。"})
        if status == RecordStatus.ACTIVE and workshop and workshop.status != RecordStatus.ACTIVE:
            raise serializers.ValidationError({"workshop": "启用工艺不能关联已停用车间。"})
        return attrs


class OperationSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(required=False, allow_blank=True, default="")
    craft_name = serializers.CharField(source="craft.name", read_only=True)
    craft_type = serializers.CharField(source="craft.craft_type", read_only=True)
    craft_type_display = serializers.CharField(source="craft.get_craft_type_display", read_only=True)
    workshop = serializers.UUIDField(source="craft.workshop_id", read_only=True, allow_null=True)
    workshop_name = serializers.CharField(source="craft.workshop.name", read_only=True, allow_null=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    reporting_unit_name = serializers.CharField(source="reporting_unit.unit_name", read_only=True, allow_null=True)

    class Meta:
        model = Operation
        fields = [
            "id", "operation_number", "product_name", "craft", "craft_name", "craft_type",
            "craft_type_display", "workshop", "workshop_name", "name", "reporting_unit", "reporting_unit_name",
            "status", "status_display",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "craft_name", "craft_type", "craft_type_display", "workshop", "workshop_name",
            "reporting_unit_name", "status_display", "created_at", "updated_at",
        ]

    def validate_operation_number(self, value):
        return _normalized_text(value, "工序编号").upper()

    def validate_product_name(self, value):
        return str(value or "").strip()

    def validate_name(self, value):
        return _normalized_text(value, "工序名称")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        craft = attrs.get("craft", getattr(self.instance, "craft", None))
        status = attrs.get("status", getattr(self.instance, "status", RecordStatus.ACTIVE))
        if status == RecordStatus.ACTIVE and craft and craft.status != RecordStatus.ACTIVE:
            raise serializers.ValidationError({"craft": "启用工序不能关联已停用工艺。"})
        product_name = attrs.get("product_name", getattr(self.instance, "product_name", "")).strip()
        is_metal_workshop = (
            craft
            and craft.workshop
            and craft.workshop.name == METAL_WORKSHOP_NAME
        )
        if is_metal_workshop:
            attrs["product_name"] = ""
        elif not product_name:
            raise serializers.ValidationError({"product_name": "非金工工序必须填写品名。"})
        if self.instance and self.instance.wage_work_items.exists():
            if craft and craft.pk != self.instance.craft_id:
                raise serializers.ValidationError({"craft": "工序已有工价工作项，不能更换所属工艺。"})
        return attrs
