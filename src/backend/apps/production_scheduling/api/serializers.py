from rest_framework import serializers

from apps.audit.models import AuditLog
from apps.production_tasks.models import ProductionTaskStatus

from ..models import ProductionSchedule, ProductionScheduleProduct


class ScheduleProductWriteSerializer(serializers.Serializer):
    product_line_id = serializers.UUIDField()
    planned_quantity = serializers.IntegerField(min_value=1)
    material_inbound_date = serializers.DateField()
    metal_return_date = serializers.DateField()
    sewing_return_date = serializers.DateField()
    finished_inbound_date = serializers.DateField()
    craft_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, allow_empty=False)

    def validate_craft_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("同一工艺不能重复选择。")
        return value


class ScheduleCreateSerializer(serializers.Serializer):
    production_task_id = serializers.UUIDField()
    source_revision_hash = serializers.CharField(min_length=64, max_length=64)
    client_request_id = serializers.UUIDField()
    items = ScheduleProductWriteSerializer(many=True, allow_empty=False)


class ScheduleBatchCreateSerializer(serializers.Serializer):
    schedules = ScheduleCreateSerializer(many=True, allow_empty=False, max_length=50)

    def validate_schedules(self, value):
        task_ids = [item["production_task_id"] for item in value]
        if len(task_ids) != len(set(task_ids)):
            raise serializers.ValidationError("同一生产任务单不能在一次批量生成中重复出现。")
        request_ids = [item["client_request_id"] for item in value]
        if len(request_ids) != len(set(request_ids)):
            raise serializers.ValidationError("批量生成中的请求标识不能重复。")
        return value


class ScheduleUpdateSerializer(serializers.Serializer):
    source_revision_hash = serializers.CharField(min_length=64, max_length=64)
    items = ScheduleProductWriteSerializer(many=True, allow_empty=False)


class ScheduleVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=2, max_length=500, trim_whitespace=True)


class ScheduleProductReadSerializer(serializers.Serializer):
    def to_representation(self, instance):
        product = instance.product_snapshot or {}
        crafts = getattr(instance, "active_crafts", None)
        if crafts is None:
            crafts = instance.crafts.filter(removed_at__isnull=True).select_related("craft")
        return {
            "id": str(instance.pk),
            "product_line_id": str(instance.product_line_id),
            "line_number": instance.line_number,
            "planned_quantity": instance.planned_quantity,
            "source_quantity": instance.source_quantity_snapshot,
            "unit_id": str(instance.unit_id),
            "unit_name": instance.unit_name_snapshot,
            "image_file_id": str(instance.image_file_id) if instance.image_file_id else None,
            "product": product,
            "material_inbound_date": instance.material_inbound_date,
            "metal_return_date": instance.metal_return_date,
            "sewing_return_date": instance.sewing_return_date,
            "finished_inbound_date": instance.finished_inbound_date,
            "crafts": [
                {
                    "id": str(link.craft_id),
                    "name": link.craft_name_snapshot,
                    "craft_type": link.craft_type_snapshot,
                    "plan_category": link.plan_category,
                    "is_active": getattr(link.craft, "status", "ACTIVE") == "ACTIVE",
                }
                for link in crafts
            ],
        }


class ScheduleReadSerializer(serializers.Serializer):
    def to_representation(self, instance):
        products = getattr(instance, "active_products", None)
        if products is None:
            products = instance.products.filter(removed_at__isnull=True).select_related("unit", "image_file").prefetch_related("crafts__craft")
        source = instance.source_snapshot or {}
        date_fields = ["material_inbound_date", "metal_return_date", "sewing_return_date", "finished_inbound_date"]
        date_ranges = {}
        products = list(products)
        for field in date_fields:
            values = sorted(getattr(item, field) for item in products)
            date_ranges[field] = {"from": values[0] if values else None, "to": values[-1] if values else None}
        audit = []
        if self.context.get("include_audit", True):
            audit = AuditLog.objects.filter(
                object_type="PRODUCTION_SCHEDULE", object_id=instance.pk
            ).order_by("-occurred_at", "-id")[:30]
        return {
            "id": str(instance.pk),
            "schedule_number": instance.schedule_number,
            "production_task_id": str(instance.production_task_id),
            "record_status": instance.record_status,
            "record_status_display": instance.get_record_status_display(),
            "version": instance.version,
            "source": source,
            "source_revision_hash": instance.source_revision_hash,
            "source_current_status": instance.production_task.status,
            "source_current_status_display": instance.production_task.get_status_display(),
            "source_is_archived": instance.production_task.archived_at is not None,
            "products": ScheduleProductReadSerializer(products, many=True).data,
            "date_ranges": date_ranges,
            "created_by": {
                "id": str(instance.created_by_employee_id),
                "name": instance.created_by_employee.display_name,
            },
            "updated_by": {
                "id": str(instance.updated_by_employee_id),
                "name": instance.updated_by_employee.display_name,
            },
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
            "void_reason": instance.void_reason,
            "voided_at": instance.voided_at,
            "audit_timeline": [
                {
                    "id": str(event.pk), "action": event.action, "actor_name": event.actor_name_snapshot,
                    "occurred_at": event.occurred_at, "after": event.after_data,
                }
                for event in audit
            ],
        }


class ScheduleItemReadSerializer(serializers.Serializer):
    def to_representation(self, instance: ProductionScheduleProduct):
        schedule = instance.schedule
        task_status = schedule.production_task.status
        job_status, job_status_display = {
            ProductionTaskStatus.COMPLETED: ("COMPLETED", "已完成"),
            ProductionTaskStatus.PAUSED: ("PAUSED", "已暂停"),
            ProductionTaskStatus.CANCELLED: ("CANCELLED", "已取消"),
        }.get(task_status, ("IN_PROGRESS", "进行中"))
        source = schedule.source_snapshot or {}
        product = instance.product_snapshot or {}
        category = self.context.get("category")
        category_crafts = [
            link.craft_name_snapshot
            for link in getattr(instance, "active_crafts", [])
            if link.craft_type_snapshot == "INTERNAL" and link.plan_category == category
        ]
        date_map = {
            "METAL": instance.metal_return_date,
            "CUTTING": instance.sewing_return_date,
            "SEWING": instance.sewing_return_date,
            "ASSEMBLY": instance.finished_inbound_date,
        }
        return {
            "id": str(instance.pk), "schedule_id": str(schedule.pk), "schedule_number": schedule.schedule_number,
            "product_line_id": str(instance.product_line_id),
            "production_task_id": str(schedule.production_task_id), "task_number": source.get("task_number", ""),
            "sales_order_number": source.get("sales_order_number"), "customer_id": source.get("customer_account_id"),
            "customer_name": source.get("customer_name", ""),
            "product": product, "planned_quantity": instance.planned_quantity, "unit_name": instance.unit_name_snapshot,
            "image_file_id": str(instance.image_file_id) if instance.image_file_id else None,
            "plan_date": date_map.get(category), "line_number": instance.line_number,
            "craft_names": category_crafts,
            "job_status": job_status, "job_status_display": job_status_display,
        }
