"""测试专用：已批准装配工价和历史报工，支持库存原有回归场景。"""
import uuid
from decimal import Decimal, ROUND_FLOOR
from django.utils import timezone
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.workshop_config.models import Workshop, Craft, Operation, WorkshopEmployee
from apps.workshop_reporting.models import WageScheme, WageSchemeCraft, WageSchemeLine, WorkItem, WorkReport, WorkReportLine


def seed_reported_assembly(product, actor, plan=None, quantity=None, operations=1):
    scheme = WageScheme.objects.filter(product_line=product, scope_craft__plan_category='ASSEMBLY').first()
    if scheme:
        return scheme
    token = uuid.uuid4().hex[:12]
    today = timezone.localdate()
    if plan is None:
        plan = ProductionScheduleProduct.objects.filter(product_line=product, removed_at__isnull=True).first()
    if plan is None:
        from apps.production_tasks.models import ProductionTask
        original_status = product.production_task.status
        ProductionTask.objects.filter(pk=product.production_task_id).update(status='READY')
        schedule = ProductionSchedule.objects.filter(production_task=product.production_task, record_status='ACTIVE').first()
        if schedule is None:
            schedule = ProductionSchedule.objects.create(schedule_number='QA-'+token, production_task=product.production_task,
                client_request_id=uuid.uuid4(), request_payload_hash=token, source_revision_hash=token,
                created_by_employee=actor, updated_by_employee=actor)
        plan = ProductionScheduleProduct.objects.create(schedule=schedule, product_line=product,
            line_number=ProductionScheduleProduct.objects.filter(schedule=schedule).count()+1,
            planned_quantity=product.quantity, source_quantity_snapshot=product.quantity, unit=product.unit,
            unit_name_snapshot=product.unit.unit_name, material_inbound_date=today, metal_return_date=today,
            sewing_return_date=today, finished_inbound_date=today, source_revision_hash=token)
        ProductionTask.objects.filter(pk=product.production_task_id).update(status=original_status)
    link = plan.crafts.filter(plan_category='ASSEMBLY', removed_at__isnull=True).select_related('craft__workshop').first()
    if link:
        craft, workshop = link.craft, link.craft.workshop
    else:
        workshop, _ = Workshop.objects.get_or_create(name='装配车间')
        craft, _ = Craft.objects.get_or_create(plan_category='ASSEMBLY', defaults={
            'name':'装配'+token, 'craft_type':'INTERNAL', 'workshop':workshop})
        workshop = craft.workshop
        ProductionScheduleProductCraft.objects.create(schedule_product=plan, craft=craft, craft_type_snapshot='INTERNAL',
            craft_name_snapshot=craft.name, plan_category='ASSEMBLY')
    scheme = WageScheme.objects.create(scheme_number='QA-GJ-'+token, product_line=product, schedule_product=plan,
        workshop=workshop, scope_craft=craft, status='APPROVED', effective_from=today,
        product_name_snapshot=product.product_name_snapshot, product_number_snapshot=product.product_number_snapshot,
        operation_product_name_snapshot=product.product_name_snapshot, created_by_employee=actor,
        updated_by_employee=actor, approved_by_employee=actor, approved_at=timezone.now())
    WageSchemeCraft.objects.create(scheme=scheme, craft=craft)
    worker = WorkshopEmployee.objects.create(workshop=workshop, position='装配', name='测试装配员'+token, is_supervisor=False)
    maximum = int((Decimal(product.quantity)*(1+Decimal(product.production_task.order_tolerance_percent)/100)).to_integral_value(rounding=ROUND_FLOOR))
    quantity = maximum if quantity is None else quantity
    report = WorkReport.objects.create(report_number='QA-BG-'+token, production_date=today, product_line=product,
        schedule_product=plan, workshop=workshop, scheme=scheme, scheme_version_snapshot=scheme.version,
        recorder_employee=actor, updated_by_employee=actor, total_amount=quantity*operations,
        client_request_id=uuid.uuid4(), request_payload_hash=token)
    for i in range(operations):
        op, _ = Operation.objects.get_or_create(product_name=product.product_name_snapshot,
            craft=craft, name=f'工序{i+1}', defaults={
                'operation_number':f'QA-OP-{token}-{i}', 'reporting_unit':product.unit})
        item = WorkItem.objects.create(product_line=product, workshop=workshop, craft=craft, operation=op,
            unit=product.unit, identity_key=f'{token}-{i}', display_name=f'工序{i+1}', counting_mode='ORDER')
        line = WageSchemeLine.objects.create(scheme=scheme, work_item=item, line_number=i+1, counting_mode='ORDER',
            display_name_snapshot=item.display_name, craft_name_snapshot=craft.name, operation_name_snapshot=op.name,
            operation_number_snapshot=op.operation_number, unit_name_snapshot=product.unit.unit_name,
            declared_price=1, order_quantity_snapshot=product.quantity, required_quantity_snapshot=max(maximum,quantity))
        if quantity:
            WorkReportLine.objects.create(report=report, line_number=i+1, scheme_line=line, work_item=item,
                workshop_employee=worker, production_line=1, quantity=quantity, order_quantity_snapshot=product.quantity,
                required_quantity_snapshot=line.required_quantity_snapshot, unit_price_snapshot=1, amount=quantity,
                display_name_snapshot=item.display_name, craft_name_snapshot=craft.name, operation_name_snapshot=op.name,
                unit_name_snapshot=product.unit.unit_name, employee_name_snapshot=worker.name)
    return scheme
