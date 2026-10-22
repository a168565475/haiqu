from django.db.models import Q
from django.db.models.fields.json import KeyTextTransform
import re
from django.db.models.functions import Coalesce, TruncDate
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.permissions import HasActiveEmployee, BusinessActionPermission
from apps.production_tasks.selectors import accessible_production_tasks
from ..internal_receipt_quantities import ReceiptQuantityError
from ..internal_receipt_services import load_receipt_context, preview_data, submit_receipt, confirm_receipt, delete_pending_receipt
from ..receipt_permissions import can_delete_pending_receipt
from ..models import (InternalReceiptStatus, PublicStockMovement, InternalSemiFinishedReceipt,
                      InternalSemiFinishedReceiptLine)


class ReceiptLineInput(serializers.Serializer):
    bom_line_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=0, min_value=1)


class ReceiptInput(serializers.Serializer):
    request_id = serializers.UUIDField()
    schedule_product_id = serializers.UUIDField()
    plan_category = serializers.ChoiceField(choices=['METAL','SEWING'])
    zone_id = serializers.UUIDField()
    receipt_date = serializers.DateField()
    remark = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    lines = ReceiptLineInput(many=True, allow_empty=False, max_length=300)


class MetalReceiptQuantity(serializers.Field):
    def to_internal_value(self, data):
        if data is None or (isinstance(data, str) and not data.strip()):
            return 0
        text = str(data).strip()
        if isinstance(data, bool) or not re.fullmatch(r'[0-9]+', text):
            raise serializers.ValidationError('本次入库须为整数支数，不支持负数、小数或文字。')
        significant = text.lstrip('0') or '0'
        if len(significant) > 14:
            raise serializers.ValidationError('本次入库数量超出范围。')
        return int(significant)


class MetalReceiptLineInput(serializers.Serializer):
    bom_line_id = serializers.UUIDField()
    quantity = MetalReceiptQuantity(allow_null=True)


class MetalReceiptInput(ReceiptInput):
    lines = MetalReceiptLineInput(many=True, allow_empty=False, max_length=300)

    def validate_lines(self, rows):
        identifiers = [row['bom_line_id'] for row in rows]
        if len(set(identifiers)) != len(identifiers):
            raise serializers.ValidationError('同一管材部位不能重复填写。')
        rows = [row for row in rows if (row['quantity'] or 0) > 0]
        if not rows:
            raise serializers.ValidationError('请至少填写一项大于0的本次入库数量。')
        return sorted(rows, key=lambda row: str(row['bom_line_id']))


class PreviewInput(serializers.Serializer):
    schedule_product_id = serializers.UUIDField()
    plan_category = serializers.ChoiceField(choices=['METAL','SEWING'])


class RecordFilter(serializers.Serializer):
    direction = serializers.ChoiceField(choices=['IN','OUT'], default='IN')
    source = serializers.ChoiceField(choices=['','INTERNAL','EXTERNAL'], default='')
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)
    product_line_id = serializers.UUIDField(required=False)

    def validate(self, data):
        if data.get('date_from') and data.get('date_to') and data['date_from'] > data['date_to']:
            raise serializers.ValidationError({'date_to':'结束日期不能早于开始日期。'})
        return data


class ReceiptResponse(serializers.Serializer):
    data = serializers.DictField()


STAGES = {'METAL':'金工完成','SEWING':'车缝完成','CUTTING':'裁剪完成','POWDER_COATING':'喷塑完成','SCREEN_PRINTING':'丝印完成','EMBROIDERY':'刺绣完成'}
TUBE_SOURCE_LABELS = {'RAW_PIPE':'原材料','PUBLIC_SEMI':'未喷塑半成品','METAL':'未入库半成品'}


def record_data(row):
    attributes = row.balance.identity_snapshot
    snapshot = row.snapshot or {}
    outgoing = row.direction == 'OUT'
    internal = row.source_type == 'INTERNAL_SEMI_RECEIPT' or (outgoing and row.source_type == 'MATERIAL_ISSUE')
    source_label = {'MATERIAL_ISSUE':'生产领用出库', 'OUTSOURCING_DISPATCH':'外发出库',
        'TUBE_OUTSOURCING_DISPATCH':'管材外发出库'}.get(row.source_type, '半成品出库') if outgoing else ('厂内入库' if internal else '外发入库')
    return dict(id=str(row.pk),receipt_number=row.business_number or snapshot.get('issue_number') or snapshot.get('dispatch_number') or snapshot.get('receipt_number') or snapshot.get('return_number') or snapshot.get('order_number') or str(row.source_id),
        direction=row.direction, source='INTERNAL' if internal else 'EXTERNAL',source_display=source_label,
        production_order=row.production_task.task_number if row.production_task_id else '',
        product=row.product_line.product_name_snapshot if row.product_line_id else '',
        attributes=attributes,stage=STAGES.get(attributes.get('completed_craft',{}).get('code'),''),
        quantity=str(row.quantity),unit=attributes.get('unit_name',''),
        receipt_date=str(row.business_date),status='已出库' if outgoing else '已入库',
        warehouse=row.balance.zone.warehouse.warehouse_name,zone=row.balance.zone.zone_name,
        actor=row.actor_employee.display_name if row.actor_employee_id else '',
        remark=snapshot.get('remark',''), can_delete=False)


def pending_record_data(receipt, request=None):
    line = receipt.lines.select_related('unit').order_by('id').first()
    attributes = (line.attribute_snapshot if line else {}) or {}
    quantity = sum((item.quantity for item in receipt.lines.all()), 0)
    return dict(
        id=str(receipt.pk), receipt_number=receipt.receipt_number, direction='IN', source='INTERNAL',
        source_display='厂内入库（待确认）', production_order=receipt.source_snapshot.get('production_order', ''),
        product=receipt.source_snapshot.get('product', ''), attributes=attributes,
        stage=STAGES.get(attributes.get('completed_craft', {}).get('code'), '厂内半成品'),
        quantity=str(quantity), unit=line.unit.unit_name if line else attributes.get('unit_name', ''),
        receipt_date=str(receipt.receipt_date), status=receipt.status,
        warehouse=receipt.zone.warehouse.warehouse_name, zone=receipt.zone.zone_name,
        actor=receipt.actor_employee.display_name if receipt.actor_employee_id else '', remark=receipt.remark,
        submitted_by=receipt.submitted_by_employee.display_name if receipt.submitted_by_employee_id else '',
        submitted_at=receipt.submitted_at.isoformat() if receipt.submitted_at else None,
        confirmed_by=None, confirmed_at=None,
        receipt_id=str(receipt.pk), etag=f'"{receipt.source_revision_hash}"',
        can_delete=can_delete_pending_receipt(request, receipt, receipt.plan_category),
        source_detail={**receipt.source_snapshot, 'source_number': receipt.receipt_number,
                       'workshop': receipt.completed_craft.name, 'status': receipt.status,
                       'remark': receipt.remark},
    )


def receipt_result(receipt, *, replayed=False):
    return {
        'receipt_id': str(receipt.pk),
        'receipt_number': receipt.receipt_number,
        'status': receipt.status,
        'submitted_at': receipt.submitted_at.isoformat() if receipt.submitted_at else None,
        'confirmed_at': receipt.confirmed_at.isoformat() if receipt.confirmed_at else None,
        'replayed': replayed,
        'record_ids': [str(value) for value in receipt.lines.values_list('stock_movement_id', flat=True) if value],
    }


def pending_data(receipt, request=None):
    return {
        **receipt_result(receipt),
        'etag': f'"{receipt.source_revision_hash}"',
        'can_delete': can_delete_pending_receipt(request, receipt, receipt.plan_category),
        'schedule_product_id': str(receipt.schedule_product_id),
        'plan_category': receipt.plan_category,
        'production_order': receipt.schedule_product.schedule.production_task.task_number,
        'receipt_date': str(receipt.receipt_date),
        'zone': receipt.zone.zone_name,
        'submitted_by': receipt.submitted_by_employee.display_name if receipt.submitted_by_employee_id else
            receipt.actor_employee.display_name,
        'lines': [
            {'id': str(line.pk), 'bom_line_id': str(line.bom_line_id), 'component_identity': str(line.component_identity),
             'quantity': str(line.quantity), 'input_quantity': str(line.input_quantity) if line.input_quantity is not None else None}
            for line in receipt.lines.all()
        ],
    }


class InternalReceiptViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = ReceiptInput
    action_permission_map = {key:'inventory.view_internalsemifinishedreceipt' for key in
                             ['preview','list','retrieve','by_request','pending']}
    action_permission_map['create'] = 'inventory.add_internalsemifinishedreceipt'
    action_permission_map['confirm'] = 'inventory.confirm_internalsemifinishedreceipt'
    action_permission_map['destroy'] = 'inventory.delete_internalsemifinishedreceipt'

    @extend_schema(request=None, parameters=[OpenApiParameter('If-Match', str, location='header', required=True)], responses={204: None})
    def destroy(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        delete_pending_receipt(request, pk)
        return Response(status=204)

    @extend_schema(parameters=[PreviewInput], responses={200:ReceiptResponse})
    @action(detail=False, methods=['get'])
    def preview(self, request):
        serializer = PreviewInput(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            context = load_receipt_context(request, serializer.validated_data['schedule_product_id'], serializer.validated_data['plan_category'])
            data = preview_data(context,request.employee)
        except ReceiptQuantityError as error:
            raise ValidationError({'detail':str(error),'code':error.code})
        return Response({'data':data}, headers={'ETag':data['etag']})

    @extend_schema(request=ReceiptInput, parameters=[OpenApiParameter('If-Match',str,location='header',required=True)], responses={200:ReceiptResponse,201:ReceiptResponse})
    def create(self, request):
        metal = isinstance(request.data, dict) and request.data.get('plan_category') == 'METAL'
        from ..tube_receipt_services import uses_tube_receipt
        tube = metal and uses_tube_receipt(schedule_product_id=request.data.get('schedule_product_id'), request_id=request.data.get('request_id'))
        input_type = MetalReceiptInput if tube else ReceiptInput
        serializer = input_type(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            receipt, replay = submit_receipt(request,serializer.validated_data)
        except ReceiptQuantityError as error:
            raise ValidationError({'detail':str(error),'code':error.code})
        return Response({'data':receipt_result(receipt, replayed=replay)}, status=200 if replay else 201)

    @extend_schema(request=None, responses={200:ReceiptResponse})
    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        try:
            receipt, replay = confirm_receipt(request, pk)
        except ReceiptQuantityError as error:
            raise ValidationError({'detail':str(error),'code':error.code})
        return Response({'data':receipt_result(receipt, replayed=replay)})

    @extend_schema(responses={200:ReceiptResponse})
    @action(detail=False, methods=['get'], url_path='pending')
    def pending(self, request):
        receipts = InternalSemiFinishedReceipt.objects.filter(
            status=InternalReceiptStatus.PENDING,
            schedule_product__schedule__production_task_id__in=accessible_production_tasks(request).values('id'),
        ).select_related('schedule_product__schedule__production_task', 'completed_craft',
                         'zone', 'submitted_by_employee', 'actor_employee').prefetch_related('lines').order_by('-submitted_at', '-id')
        return Response({'data': {'total': receipts.count(), 'items': [pending_data(receipt, request) for receipt in receipts]}})

    @action(detail=False, methods=['get'], url_path=r'by-request/(?P<request_id>[^/.]+)')
    def by_request(self, request, request_id=None):
        from ..tube_receipt_services import require_receipt_recovery_access, receipt_result
        request_id = serializers.UUIDField().run_validation(request_id)
        receipt = get_object_or_404(InternalSemiFinishedReceipt.objects.select_related('schedule_product'), request_id=request_id)
        require_receipt_recovery_access(request, receipt)
        return Response({'data': receipt_result(receipt)})

    def records(self, request):
        params = RecordFilter(data=request.query_params)
        params.is_valid(raise_exception=True)
        if params.validated_data['direction'] == 'OUT':
            return PublicStockMovement.objects.filter(direction='OUT', balance__stock_kind='SEMI',
                production_task_id__in=accessible_production_tasks(request).values('id')).select_related(
                    'balance__zone__warehouse','production_task','product_line','actor_employee').annotate(
                        business_number=KeyTextTransform('issue_number', 'snapshot'),
                        business_date=TruncDate('occurred_at')).order_by('-occurred_at','-id')
        return PublicStockMovement.objects.filter(direction='IN',balance__stock_kind='SEMI',
            production_task_id__in=accessible_production_tasks(request).values('id'),
                    source_type__in=['INTERNAL_SEMI_RECEIPT','OUTSOURCING_RETURN','METAL_P4_EXTERNAL_RETURN','TUBE_OUTSOURCING_RETURN']).select_related(
                'balance__zone__warehouse','production_task','product_line','actor_employee').annotate(
                    business_number=Coalesce('internal_receipt_line__receipt__receipt_number','outsourcing_return_line__return_record__return_number','metal_processing_good_return__return_number','tube_outsourcing_receipt_line__receipt__receipt_number'),
                    business_date=Coalesce('internal_receipt_line__receipt__receipt_date',
                        'outsourcing_return_line__return_record__return_date','metal_processing_good_return__return_date',
                        'tube_outsourcing_receipt_line__receipt__receipt_date',
                        TruncDate('occurred_at'))).order_by('-created_at','-id')

    @extend_schema(parameters=[RecordFilter],responses={200:ReceiptResponse})
    def list(self,request):
        serializer = RecordFilter(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        rows = self.records(request)
        internal_source = 'MATERIAL_ISSUE' if params['direction'] == 'OUT' else 'INTERNAL_SEMI_RECEIPT'
        if params['source'] == 'INTERNAL':
            rows = rows.filter(source_type=internal_source)
        elif params['source'] == 'EXTERNAL':
            rows = rows.exclude(source_type=internal_source)
        if params.get('search'):
            value = params['search']
            rows = rows.filter(Q(production_task__task_number__icontains=value) | Q(product_line__product_name_snapshot__icontains=value)
                | Q(balance__identity_snapshot__part_name__icontains=value) | Q(business_number__icontains=value)
                | Q(snapshot__order_number__icontains=value) | Q(snapshot__receipt_number__icontains=value))
        if params.get('product_line_id'):
            rows = rows.filter(product_line_id=params['product_line_id'])
        if params.get('date_from'):
            rows = rows.filter(business_date__gte=params['date_from'])
        if params.get('date_to'):
            rows = rows.filter(business_date__lte=params['date_to'])
        if params['direction'] == 'IN':
            pending = InternalSemiFinishedReceipt.objects.filter(
                status=InternalReceiptStatus.PENDING,
                schedule_product__schedule__production_task_id__in=accessible_production_tasks(request).values('id'),
            ).select_related('zone__warehouse', 'completed_craft', 'actor_employee', 'submitted_by_employee').prefetch_related('lines__unit')
            if params['source'] == 'EXTERNAL':
                pending = pending.none()
            if params.get('product_line_id'):
                pending = pending.filter(schedule_product__product_line_id=params['product_line_id'])
            if params.get('date_from'):
                pending = pending.filter(receipt_date__gte=params['date_from'])
            if params.get('date_to'):
                pending = pending.filter(receipt_date__lte=params['date_to'])
            pending_items = [pending_record_data(item, request) for item in pending]
            if params.get('search'):
                value = params['search'].lower()
                pending_items = [item for item in pending_items if value in ' '.join([
                    item['receipt_number'], item['production_order'], item['product'], item['source_display']]).lower()]
            confirmed_items = [record_data(row) for row in rows]
            items = sorted([*confirmed_items, *pending_items], key=lambda item: item['receipt_date'], reverse=True)
            start = (params['page'] - 1) * params['page_size']
            return Response({'data': {'total': len(items), 'items': items[start:start + params['page_size']]}})
        start = (params['page']-1)*params['page_size']
        return Response({'data':{'total':rows.count(),'items':[record_data(row) for row in rows[start:start+params['page_size']]]}})

    @extend_schema(responses={200:ReceiptResponse})
    def retrieve(self,request,pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        pending = InternalSemiFinishedReceipt.objects.filter(
            pk=pk, status=InternalReceiptStatus.PENDING,
            schedule_product__schedule__production_task_id__in=accessible_production_tasks(request).values('id'),
        ).select_related('zone__warehouse', 'completed_craft', 'actor_employee', 'submitted_by_employee').prefetch_related('lines__unit').first()
        if pending is not None:
            return Response({'data': pending_record_data(pending, request)})
        row = get_object_or_404(self.records(request),pk=pk)
        data = record_data(row)
        if row.direction == 'OUT':
            data['source_detail'] = {'before_quantity':str(row.before_quantity), 'after_quantity':str(row.after_quantity)}
            return Response({'data':data})
        if row.source_type == 'INTERNAL_SEMI_RECEIPT':
            line = get_object_or_404(InternalSemiFinishedReceiptLine.objects.select_related('receipt__completed_craft'),stock_movement=row)
            data['source_detail'] = {**line.receipt.source_snapshot,'source_number':line.receipt.receipt_number,
                'workshop':line.receipt.completed_craft.name,'required':str(line.required_quantity_snapshot),
                'received_before':str(line.received_before),'received_after':str(line.received_after),
                'input_quantity':str(line.input_quantity) if line.input_quantity is not None else None,
                'input_unit':line.input_unit_name,'remark':line.receipt.remark}
        else:
            data['source_detail'] = {'source_number':row.snapshot.get('order_number',''),
                'factory':row.snapshot.get('factory_name') or row.snapshot.get('factory',''),'source_id':str(row.source_id),
                'returned_quantity':str(row.quantity),'remark':row.snapshot.get('remark','')}
            if row.source_type == 'OUTSOURCING_RETURN':
                from apps.outsourcing.models import OutsourcingReturnLine
                original = OutsourcingReturnLine.objects.filter(public_stock_movement=row).select_related(
                    'return_record__order','return_record__factory','allocation__factory').first()
                if original:
                    record = original.return_record
                    data['source_detail'].update(source_number=record.order.order_number,
                        factory=record.factory_snapshot.get('name') or original.allocation.factory_snapshot.get('name') or original.allocation.factory.name,
                        remark=record.remark,delivery_note_number=record.delivery_note_number)
            elif row.source_type == 'METAL_P4_EXTERNAL_RETURN':
                from apps.material_issues.models import MetalProcessingExternalGoodReturn
                original = MetalProcessingExternalGoodReturn.objects.filter(public_stock_movement=row).select_related('order__factory').first()
                if original:
                    data['source_detail'].update(source_number=original.order.order_number,
                        factory=original.snapshot.get('factory_name') or original.order.factory.name,remark=original.remark)
            elif row.source_type == 'TUBE_OUTSOURCING_RETURN':
                snapshot = row.snapshot or {}
                identity = snapshot.get('public_identity') if isinstance(snapshot.get('public_identity'), dict) else {}
                identity_snapshot = identity.get('identity_snapshot') if isinstance(identity.get('identity_snapshot'), dict) else {}
                source_kind = str(snapshot.get('source_kind') or '')
                data['source_detail'].update(
                    source_type=row.source_type,
                    source_number=str(snapshot.get('order_number') or ''),
                    receipt_number=str(snapshot.get('receipt_number') or data['receipt_number']),
                    source_kind=source_kind,
                    source_kind_label=TUBE_SOURCE_LABELS.get(source_kind, source_kind),
                    factory=str(snapshot.get('factory_name') or ''),
                    dispatched_quantity=str(snapshot.get('dispatched_quantity') or ''),
                    received_quantity=str(snapshot.get('quantity') or row.quantity),
                    returned_quantity=str(snapshot.get('quantity') or row.quantity),
                    shortage_quantity=str(snapshot.get('shortage_quantity') or '0'),
                    shortage_reason=str(snapshot.get('shortage_reason') or ''),
                    raw_color=str(snapshot.get('raw_color') or ''),
                    spray_color=str(snapshot.get('spray_color') or identity_snapshot.get('color') or ''),
                    remark=str(snapshot.get('remark') or ''),
                )
        return Response({'data':data})
