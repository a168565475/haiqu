from apps.access_control.resource_scopes import can_order
from decimal import Decimal

from rest_framework import serializers

from ..models import OutsourcingFactory, OutsourcingOrder


def _dispatched_revocation_blocker(order):
    from ..reconciliation_services import dispatched_revocation_blocker

    return dispatched_revocation_blocker(order)


def _decimal_text(value):
    return None if value is None else format(value, "f")


def _money_text(value):
    return None if value is None else format(value.quantize(Decimal("0.0001")), "f")


def _return_line_attributes(line):
    """读取回货时冻结的部件属性，旧记录再回退到加工快照。"""
    processing = line.allocation.processing_item
    component = processing.component_snapshot or {}
    snapshot = line.snapshot or {}
    return {
        "component": snapshot.get("component") or component.get("part_name", ""),
        "specification": component.get("specification", ""),
        "color": snapshot.get("color") or component.get("color", ""),
        "bom_attributes": component.get("bom_attributes", []),
    }


class FactoryWriteSerializer(serializers.Serializer):
    # D01 尚未确认前，界面和写接口都只允许一次提交一项工艺，避免提前产生多工艺数据。
    craft_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=1, allow_empty=False)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    processing_type = serializers.CharField(max_length=200, trim_whitespace=True)
    estimated_output = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"), allow_null=True, required=False)
    estimated_output_unit = serializers.CharField(max_length=50, trim_whitespace=True, allow_blank=True, required=False, default="")
    estimated_output_period = serializers.CharField(max_length=50, trim_whitespace=True, allow_blank=True, required=False, default="")
    contact_name = serializers.CharField(max_length=100, trim_whitespace=True)
    contact_phone = serializers.CharField(max_length=100, trim_whitespace=True)
    address = serializers.CharField(max_length=500, trim_whitespace=True)
    remark = serializers.CharField(allow_blank=True, required=False, default="", trim_whitespace=True)
    payment_cycle = serializers.ChoiceField(choices=[("MONTHLY", "月结")], default="MONTHLY")

    def validate_craft_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("工艺不能重复选择。")
        return value


class FactoryReadSerializer(serializers.Serializer):
    def to_representation(self, instance: OutsourcingFactory):
        links = getattr(instance, "prefetched_craft_links", None)
        if links is None:
            links = instance.craft_links.select_related("craft").all()
        return {
            "id": str(instance.pk),
            "factory_number": instance.factory_number,
            "name": instance.name,
            "crafts": [
                {"id": str(link.craft_id), "name": link.craft_name_snapshot}
                for link in links
            ],
            "processing_type": instance.processing_type,
            "estimated_output": instance.estimated_output,
            "estimated_output_unit": instance.estimated_output_unit,
            "estimated_output_period": instance.estimated_output_period,
            "contact_name": instance.contact_name,
            "contact_phone": instance.contact_phone,
            "address": instance.address,
            "remark": instance.remark,
            "payment_cycle": instance.payment_cycle,
            "payment_cycle_display": instance.get_payment_cycle_display(),
            "status": instance.status,
            "status_display": instance.get_status_display(),
            "version": instance.version,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }


class OutsourcingOrderReadSerializer(serializers.Serializer):
    def to_representation(self, instance: OutsourcingOrder):
        from apps.material_issues.p4_services import DIRECT_HANDOFF_LOCK_REASON, has_original_direct_handoff
        direct_handoff = has_original_direct_handoff(instance)
        products = getattr(instance, "prefetched_products", None)
        if products is None:
            products = instance.products.all()
        products = list(products)
        allocations = []
        allocation_entries = []
        processing_count = 0
        for product in products:
            items = getattr(product, "prefetched_processing_items", None)
            if items is None:
                items = product.processing_items.select_related("unit").prefetch_related("allocations__factory").all()
            items = list(items)
            processing_count += len(items)
            for item in items:
                item_allocations = getattr(item, "prefetched_allocations", None)
                if item_allocations is None:
                    item_allocations = list(item.allocations.select_related("factory").all())
                allocations.extend(item_allocations)
                allocation_entries.extend((product, allocation) for allocation in item_allocations)
        target_factory_id = str(self.context.get("factory_id", ""))
        target_entries = [
            (product, allocation)
            for product, allocation in allocation_entries
            if str(allocation.factory_id) == target_factory_id
        ] if target_factory_id else []
        target_products_by_id = {str(product.pk): product for product, _allocation in target_entries}
        display_products = list(target_products_by_id.values()) if target_factory_id else products
        first_product = display_products[0] if display_products else None
        product = first_product.product_snapshot if first_product else {}
        factory_names_by_id = {
            str(allocation.factory_id): allocation.factory_snapshot.get("name", allocation.factory.name)
            for allocation in allocations
        }
        planned_amount = sum(
            (allocation.allocated_quantity * allocation.unit_price for allocation in allocations), Decimal("0")
        )
        target_allocations = [allocation for _product, allocation in target_entries]
        # 不同 BOM 单位不能直接相加；仅单一分配行时返回数量与单位。
        factory_allocated_quantity = (
            _decimal_text(target_allocations[0].allocated_quantity) if len(target_allocations) == 1 else None
        )
        factory_allocated_unit = (
            target_allocations[0].processing_item.unit_snapshot if len(target_allocations) == 1 else None
        )
        action_candidates = self.context.get("action_candidates")
        delete_candidate = (
            instance.pk in action_candidates["delete"] if action_candidates is not None
            else instance.status == "PENDING_DISPATCH" and not instance.return_records.exists()
            and not hasattr(instance, "dispatch_record")
        )
        revoke_candidate = (
            instance.pk in action_candidates["revoke_dispatched"] if action_candidates is not None
            else instance.status == "PROCESSING" and not _dispatched_revocation_blocker(instance)
        )
        return {
            "id": str(instance.pk),
            "order_number": instance.order_number,
            "stock_mode": instance.stock_mode,
            "schedule_id": str(instance.schedule_id),
            "schedule_number": instance.schedule.schedule_number,
            "production_task_number": instance.schedule.production_task.task_number,
            "craft": {"id": str(instance.craft_id), "name": instance.craft_name_snapshot},
            "delivery_date": instance.delivery_date,
            "status": instance.status,
            "status_display": instance.get_status_display(),
            "product": product,
            "product_count": len(display_products),
            "processing_count": processing_count,
            "returned_processing_count": None,
            "factory_names": list(factory_names_by_id.values()),
            "factory_count": len(factory_names_by_id),
            "planned_amount": _money_text(planned_amount),
            "factory_allocated_quantity": factory_allocated_quantity,
            "factory_allocated_unit": factory_allocated_unit,
            "factory_allocation_count": len(target_allocations) if target_factory_id else None,
            "factory_returned_quantity": None,
            "factory_remaining_quantity": None,
            "direct_handoff": direct_handoff,
            "direct_handoff_lock_reason": DIRECT_HANDOFF_LOCK_REASON if direct_handoff else "",
            "can_delete": bool(
                not direct_handoff and delete_candidate
                and self.context.get("request")
                and can_order(self.context["request"], "outsourcing.delete_outsourcingorder", instance)
            ),
            "can_revoke_dispatched": bool(
                self.context.get("request")
                and can_order(self.context["request"], "outsourcing.cancel_outsourcingorder", instance)
                and can_order(self.context["request"], "outsourcing.return_raw_outsourcingorder", instance)
                and not direct_handoff
                and revoke_candidate
            ),
            "updated_at": instance.updated_at,
        }


class OutsourcingOrderCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class OutsourcingOrderRevokeSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class OutsourcingDispatchLineWriteSerializer(serializers.Serializer):
    material_item_id = serializers.UUIDField()
    inbound_line_id = serializers.UUIDField(required=False)
    zone_id = serializers.UUIDField(required=False)
    requested_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    conversion_factor = serializers.DecimalField(
        max_digits=22,
        decimal_places=8,
        min_value=Decimal("0.00000001"),
        default=Decimal("1"),
    )
    conversion_evidence = serializers.CharField(max_length=1000, allow_blank=True, required=False, default="")
    match_method = serializers.ChoiceField(
        choices=[("BOM_LINE", "BOM 明细"), ("REFERENCE_ID", "稳定原料 ID"), ("MANUAL_CONFIRMED", "人工核对")],
        default="REFERENCE_ID",
    )
    match_reason = serializers.CharField(max_length=1000, allow_blank=True, required=False, default="")

    def validate(self, attrs):
        if ("inbound_line_id" in attrs) == ("zone_id" in attrs):
            raise serializers.ValidationError("请选择库区；兼容旧请求时只能提供批次或库区之一。")
        return attrs


class OutsourcingDispatchConfirmSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    lines = OutsourcingDispatchLineWriteSerializer(many=True, allow_empty=False)
    remark = serializers.CharField(max_length=1000, allow_blank=True, required=False, default="", trim_whitespace=True)

    def validate_lines(self, value):
        pairs = [(item["material_item_id"], item.get("inbound_line_id") or item.get("zone_id")) for item in value]
        if len(pairs) != len(set(pairs)):
            raise serializers.ValidationError("同一计划材料不能重复选择同一库区或批次。")
        source_modes = {}
        for item in value:
            material_id = item["material_item_id"]
            mode = "zone" if item.get("zone_id") else "batch"
            if material_id in source_modes and source_modes[material_id] != mode:
                raise serializers.ValidationError("同一计划材料不能混用库区和批次发料。")
            source_modes[material_id] = mode
        return value


class OutsourcingReturnLineWriteSerializer(serializers.Serializer):
    allocation_id = serializers.UUIDField()
    good_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    defective_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    defect_reason = serializers.CharField(max_length=1000, allow_blank=True, required=False, default="", trim_whitespace=True)

    def validate(self, attrs):
        if attrs["good_quantity"] + attrs["defective_quantity"] <= 0:
            raise serializers.ValidationError("本批实收数量必须大于 0。")
        if attrs["defective_quantity"] > 0 and not attrs["defect_reason"]:
            raise serializers.ValidationError("存在不良数量时必须填写不良原因。")
        return attrs


class ReconciliationEntrySerializer(serializers.Serializer):
    allocation_id = serializers.UUIDField()
    dispatch_line_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    kind = serializers.ChoiceField(choices=["RAW_INPUT", "RAW_LOSS", "OUTPUT_SCRAP"])
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class ReconciliationWriteSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    entries = ReconciliationEntrySerializer(many=True, allow_empty=False)


class RawReturnLineSerializer(serializers.Serializer):
    dispatch_line_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))


class RawReturnWriteSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    factory_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)
    lines = RawReturnLineSerializer(many=True, allow_empty=False)


class CompleteWriteSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()


class OutsourcingReturnConfirmSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    factory_id = serializers.UUIDField()
    good_zone_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    defective_zone_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    received_by_employee_id = serializers.UUIDField()
    return_date = serializers.DateField()
    delivery_note_number = serializers.CharField(max_length=100, allow_blank=True, required=False, default="", trim_whitespace=True)
    lines = OutsourcingReturnLineWriteSerializer(many=True, allow_empty=False)
    raw_inputs = ReconciliationEntrySerializer(many=True, required=False, default=list)
    remark = serializers.CharField(max_length=1000, allow_blank=True, required=False, default="", trim_whitespace=True)

    def validate_lines(self, value):
        allocation_ids = [item["allocation_id"] for item in value]
        if len(allocation_ids) != len(set(allocation_ids)):
            raise serializers.ValidationError("同一加工分配行不能重复填写。")
        return value


class OutsourcingOrderDetailSerializer(serializers.Serializer):
    def to_representation(self, instance: OutsourcingOrder):
        from apps.material_issues.p4_services import DIRECT_HANDOFF_LOCK_REASON, has_original_direct_handoff, original_direct_handoff_summary
        direct_handoff = has_original_direct_handoff(instance)
        direct_summary = original_direct_handoff_summary(instance) if direct_handoff else []
        direct_by_allocation = {row["allocation_id"]: row for row in direct_summary}
        source = instance.schedule.source_snapshot or {}
        production_task = instance.schedule.production_task
        products = getattr(instance, "prefetched_products", None)
        if products is None:
            products = instance.products.all()
        product_rows = []
        planned_amount = Decimal("0")
        factory_names = {}
        for product in products:
            processing_rows = []
            items = getattr(product, "prefetched_processing_items", None)
            if items is None:
                items = product.processing_items.select_related("unit").all()
            for item in items:
                allocation_rows = []
                allocations = getattr(item, "prefetched_allocations", None)
                if allocations is None:
                    allocations = item.allocations.select_related("factory").prefetch_related("material_items").all()
                for allocation in allocations:
                    factory_name = allocation.factory_snapshot.get("name") or allocation.factory.name
                    factory_names[str(allocation.factory_id)] = factory_name
                    planned_amount += allocation.allocated_quantity * allocation.unit_price
                    materials = getattr(allocation, "prefetched_material_items", None)
                    if materials is None:
                        materials = allocation.material_items.all()
                    prefetched_return_lines = getattr(allocation, "prefetched_return_lines", None)
                    if prefetched_return_lines is None:
                        prefetched_return_lines = allocation.return_lines.all()
                    returned_quantity = sum(
                        (line.returned_quantity for line in prefetched_return_lines),
                        Decimal("0"),
                    )
                    direct_allocation = direct_by_allocation.get(str(allocation.pk))
                    allocation_rows.append({
                        "id": str(allocation.pk),
                        "factory_id": str(allocation.factory_id),
                        "factory_name": factory_name,
                        "allocated_quantity": _decimal_text(allocation.allocated_quantity),
                        "input_quantity": _decimal_text(allocation.input_quantity),
                        "input_unit": allocation.input_unit_snapshot,
                        "conversion_snapshot": allocation.conversion_snapshot,
                        "unit": item.unit_snapshot,
                        "unit_price": _decimal_text(allocation.unit_price),
                        "planned_amount": _money_text(allocation.allocated_quantity * allocation.unit_price),
                        "remark": allocation.remark,
                        "returned_quantity": _decimal_text(returned_quantity),
                        "remaining_quantity": _decimal_text(Decimal(direct_allocation["remaining_return_pieces"]) if direct_allocation else (Decimal(0) if direct_handoff else max(allocation.allocated_quantity - returned_quantity, Decimal("0")))),
                        "materials": [
                            {
                                "id": str(material.pk),
                                "bom_line_id": str(material.bom_material_line_id),
                                "material_number": material.material_snapshot.get("material_number", ""),
                                "name": material.material_snapshot.get("name", ""),
                                "specification": material.material_snapshot.get("specification", ""),
                                "color": material.material_snapshot.get("color", ""),
                                "material": material.material_snapshot.get("material") or next((
                                    field.get("value", "") for field in material.material_snapshot.get("bom_attributes", [])
                                    if field.get("key") == "material"
                                ), ""),
                                "unit_consumption": (
                                    str(material.material_snapshot.get("unit_consumption") or "").strip()
                                    or _decimal_text(material.consumption_per_set)
                                ),
                                "bom_attributes": material.material_snapshot.get("bom_attributes", []),
                                "category_label": material.material_snapshot.get("category_label", ""),
                                "unit": material.unit_text,
                                "reference_required_quantity": _decimal_text(material.reference_required_quantity),
                                "planned_issue_quantity": _decimal_text(material.planned_issue_quantity),
                                "planned_piece_count": material.planned_piece_count,
                                "planned_meters": _decimal_text(material.planned_meters),
                                "conversion_snapshot": material.conversion_snapshot,
                                "difference_reason": material.difference_reason,
                                "remark": material.remark,
                            }
                            for material in materials
                        ],
                    })
                processing_rows.append({
                    "id": str(item.pk),
                    "bom_line_id": str(item.bom_line_id),
                    "part_name": item.component_snapshot.get("part_name", ""),
                    "category": item.component_snapshot.get("category", ""),
                    "specification": item.component_snapshot.get("specification", ""),
                    "color": item.component_snapshot.get("color", ""),
                    "bom_attributes": item.component_snapshot.get("bom_attributes", []),
                    "quantity": _decimal_text(item.quantity),
                    "unit": item.unit_snapshot,
                    "processing_requirement": item.processing_requirement,
                    "allocations": allocation_rows,
                })
            product_rows.append({
                "id": str(product.pk),
                "schedule_product_id": str(product.schedule_product_id),
                "image_file_id": (
                    str(product.schedule_product.image_file_id)
                    if product.schedule_product.image_file_id
                    else None
                ),
                "unit_name": product.schedule_product.unit_name_snapshot,
                "bom_id": str(product.bom_id),
                "bom_number": product.bom_number_snapshot,
                "bom_version": product.bom_version_snapshot,
                "product": product.product_snapshot,
                "order_quantity": product.order_quantity_snapshot,
                "planned_quantity": product.planned_quantity_snapshot,
                "processing_items": processing_rows,
            })
        dispatch = getattr(instance, "dispatch_record", None)
        returns = []
        return_records = getattr(instance, "prefetched_return_records", None)
        if return_records is None:
            return_records = instance.return_records.select_related(
                "factory", "zone", "defective_zone", "received_by_employee", "confirmed_by_employee"
            ).prefetch_related("lines").order_by("confirmed_at", "id")
        for record in return_records:
            return_lines = getattr(record, "prefetched_lines", None)
            if return_lines is None:
                return_lines = list(record.lines.select_related(
                    "allocation__processing_item__unit",
                ).order_by("id"))
            has_good = any(line.quality == "AVAILABLE" for line in return_lines)
            returns.append({
                "id": str(record.pk),
                "return_number": record.return_number,
                "factory_id": str(record.factory_id) if record.factory_id else None,
                "factory_name": record.factory_snapshot.get("name", ""),
                "return_date": record.return_date,
                "delivery_note_number": record.delivery_note_number,
                "zone_id": str(record.zone_id) if has_good else None,
                "zone_name": record.zone.zone_name if has_good else "",
                "defective_zone_id": str(record.defective_zone_id) if record.defective_zone_id else None,
                "defective_zone_name": record.defective_zone.zone_name if record.defective_zone_id else "",
                "received_by": (
                    record.received_by_employee.display_name
                    if record.received_by_employee_id
                    else record.confirmed_by_employee.display_name
                ),
                "confirmed_at": record.confirmed_at,
                "confirmed_by": record.confirmed_by_employee.display_name,
                "remark": record.remark,
                "lines": [
                    {
                        "id": str(line.pk),
                        "allocation_id": str(line.allocation_id),
                        "returned_quantity": _decimal_text(line.returned_quantity),
                        "unit": line.allocation.processing_item.unit_snapshot,
                        "quality": line.quality,
                        "quality_display": line.get_quality_display(),
                        "balance_id": str(line.public_stock_movement.balance_id if line.public_stock_movement_id else line.semi_finished_balance_id),
                        "stock_mode": instance.stock_mode,
                        "public_stock_movement_id": str(line.public_stock_movement_id) if line.public_stock_movement_id else None,
                        **_return_line_attributes(line),
                    }
                    for line in return_lines
                ],
            })
        request = self.context.get("request")
        can_cancel = bool(
            not direct_handoff and instance.status == "PENDING_DISPATCH"
            and request
            and can_order(request, "outsourcing.cancel_outsourcingorder", instance)
        )
        can_delete = bool(
            not direct_handoff and instance.status == "PENDING_DISPATCH"
            and request
            and can_order(request, "outsourcing.delete_outsourcingorder", instance)
            and dispatch is None and not returns
        )
        can_revoke_dispatched = bool(
            request and can_order(request, "outsourcing.cancel_outsourcingorder", instance)
            and can_order(request, "outsourcing.return_raw_outsourcingorder", instance)
            and not direct_handoff and instance.status == "PROCESSING"
            and not _dispatched_revocation_blocker(instance)
        )
        dispatch_lines = []
        if dispatch:
            dispatch_lines = getattr(dispatch, "prefetched_lines", None)
            if dispatch_lines is None:
                dispatch_lines = list(dispatch.lines.select_related("unit").order_by("id"))
        return {
            "id": str(instance.pk),
            "order_number": instance.order_number,
            "stock_mode": instance.stock_mode,
            "schedule_id": str(instance.schedule_id),
            "schedule_number": instance.schedule.schedule_number,
            "production_task_id": str(instance.schedule.production_task_id),
            "production_task_number": instance.schedule.production_task.task_number,
            "sales_order_number": (
                source.get("sales_order_number")
                or source.get("order_number")
                or production_task.order_number
                or ""
            ),
            "customer_name": (
                source.get("customer_name")
                or (production_task.customer_account.account_name if production_task.customer_account_id else "")
            ),
            "order_date": source.get("order_date") or production_task.order_date.isoformat(),
            "craft": {
                "id": str(instance.craft_id),
                "name": instance.craft_name_snapshot,
                "outsourcing_code": instance.craft_code_snapshot,
            },
            "delivery_date": instance.delivery_date,
            "status": instance.status,
            "status_display": instance.get_status_display(),
            "remark": instance.remark,
            "version": instance.version,
            "created_by": {
                "id": str(instance.created_by_employee_id),
                "name": instance.created_by_employee.display_name,
            },
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
            "planned_amount": _money_text(planned_amount),
            "factory_names": list(factory_names.values()),
            "products": product_rows,
            "can_cancel": can_cancel,
            "can_delete": can_delete,
            "can_revoke_dispatched": can_revoke_dispatched,
            "can_edit": False,
            "direct_handoff": direct_handoff,
            "direct_handoff_lock_reason": DIRECT_HANDOFF_LOCK_REASON if direct_handoff else "",
            "direct_handoff_summary": direct_summary,
            "can_confirm_dispatch": bool(
                not direct_handoff and instance.status == "PENDING_DISPATCH"
                and request
                and can_order(request, "outsourcing.confirm_dispatch_outsourcingorder", instance)
            ),
            "can_confirm_return": bool(
                not direct_handoff and instance.status in {"PROCESSING", "PARTIAL_RETURN"}
                and request
                and can_order(request, "outsourcing.confirm_return_outsourcingorder", instance)
            ),
            "dispatch": (
                {
                    "id": str(dispatch.pk),
                    "dispatch_number": dispatch.dispatch_number,
                    "dispatch_date": dispatch.dispatch_date,
                    "confirmed_at": dispatch.confirmed_at,
                    "confirmed_by": dispatch.confirmed_by_employee.display_name,
                    "line_count": len(dispatch_lines),
                    "remark": dispatch.remark,
                    "lines": [
                        {
                            "id": str(line.pk),
                            "material_item_id": str(line.material_item_id),
                            "stock_mode": instance.stock_mode,
                            "public_stock_balance_id": str(line.public_stock_balance_id) if line.public_stock_balance_id else None,
                            "public_stock_movement_id": str(line.public_stock_movement_id) if line.public_stock_movement_id else None,
                            "issued_piece_count": line.issued_piece_count,
                            "issued_meters": _decimal_text(line.issued_meters),
                            "conversion_snapshot": line.snapshot,
                            "inbound_line_id": str(line.inbound_line_id) if line.inbound_line_id else None,
                            "inbound_number": line.source_snapshot.get("inbound_number", ""),
                            "warehouse_name": line.source_snapshot.get("warehouse", ""),
                            "zone_name": line.source_snapshot.get("zone", ""),
                            "location_name": line.source_snapshot.get("location", ""),
                            "source_quantity": _decimal_text(line.source_quantity or line.issued_quantity),
                            "source_unit": line.source_unit_snapshot or line.unit.unit_name,
                            "material_quantity": _decimal_text(line.material_quantity or line.issued_quantity),
                            "material_unit": line.unit.unit_name,
                        }
                        for line in dispatch_lines
                    ],
                }
                if dispatch
                else None
            ),
            "returns": returns,
            "completed_at": instance.completed_at,
            "can_return_raw": bool(not direct_handoff and request and instance.status in {"PROCESSING", "PARTIAL_RETURN"} and can_order(request, "outsourcing.return_raw_outsourcingorder", instance)),
            "can_reconcile": bool(not direct_handoff and request and instance.status in {"PROCESSING", "PARTIAL_RETURN"} and can_order(request, "outsourcing.reconcile_outsourcingorder", instance)),
            "can_complete": bool(not direct_handoff and request and instance.status in {"PROCESSING", "PARTIAL_RETURN"} and can_order(request, "outsourcing.complete_outsourcingorder", instance)),
        }
