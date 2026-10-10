from django.db.models import Q, Sum, Count
from django.db.models.functions import Coalesce, TruncDate
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.production_scheduling.selectors import schedule_items_for_category
from ..assembly_receipts import load_context, confirm_assembly_receipt, assembly_progress_for_plans
from ..models import FinishedGoodsReceipt
from ..selectors import receipt_batches
from .serializers import FinishedGoodsReceiptSerializer


class DataResponse(serializers.Serializer):
    data = serializers.DictField()


class AssemblyInput(serializers.Serializer):
    request_id = serializers.UUIDField()
    schedule_product_id = serializers.UUIDField()
    location_id = serializers.UUIDField()
    receipt_date = serializers.DateField()
    received_quantity = serializers.IntegerField(min_value=1, max_value=9007199254740991)
    quantity_per_box = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=9007199254740991, default=None)
    actual_color = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    remark = serializers.CharField(required=False, allow_blank=True, max_length=3000, default='')


class Filters(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, max_length=150, default='')
    source = serializers.ChoiceField(choices=['','ASSEMBLY','PRODUCTION_ORDER','SAMPLE_INVENTORY'], default='')
    warehouse_id = serializers.UUIDField(required=False)
    zone_id = serializers.UUIDField(required=False)
    schedule_product_id = serializers.UUIDField(required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)


def read_data(serializer_class, data):
    serializer=serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def record_queryset():
    return receipt_batches().select_related('assembly_source').annotate(
        business_date=Coalesce('assembly_source__receipt_date', TruncDate('received_at')))


def record_payload(row):
    result = dict(FinishedGoodsReceiptSerializer(row).data)
    source = getattr(row,'assembly_source',None)
    result.update(receipt_date=str(row.business_date), schedule_number='', received_before=None, received_after=None,
        maximum_receivable=None, source_type_display='生产入库' if row.source_type=='PRODUCTION_ORDER' else row.get_source_type_display())
    if source:
        result.update(source_type='ASSEMBLY',source_type_display='装配入库',
            schedule_number=source.snapshot.get('schedule_number',''),
            received_before=source.snapshot.get('received_total'),received_after=source.snapshot.get('received_after'),
            maximum_receivable=source.snapshot.get('maximum_receivable'))
    return result


class AssemblyReceiptViewSet(viewsets.ViewSet):
    permission_classes=[IsAuthenticated,HasActiveEmployee,BusinessActionPermission]
    serializer_class=DataResponse
    action_permission_map={key:'inventory.add_finishedgoodsreceipt' for key in ['preview','create','candidates']}

    @action(detail=False,methods=['get'])
    def preview(self,request):
        class Input(serializers.Serializer):
            schedule_product_id=serializers.UUIDField()
        data=read_data(Input,request.query_params)
        _,_,result,etag=load_context(request,data['schedule_product_id'])
        result['etag']=etag
        return Response({'data':result},headers={'ETag':etag})

    @action(detail=False,methods=['get'])
    def candidates(self,request):
        data=read_data(Filters,request.query_params)
        rows=schedule_items_for_category(request,'ASSEMBLY').filter(schedule__production_task__status='IN_PRODUCTION')
        if data['q']:
            rows=rows.filter(Q(schedule__schedule_number__icontains=data['q'])|Q(product_line__product_name_snapshot__icontains=data['q'])|Q(schedule__production_task__task_number__icontains=data['q']))
        total=rows.count(); start=(data['page']-1)*data['page_size']
        plans=list(rows.order_by('-schedule__created_at','id')[start:start+data['page_size']])
        progress=assembly_progress_for_plans(plans)
        values=[dict(id=str(p.pk),schedule_number=p.schedule.schedule_number,task_number=p.schedule.production_task.task_number,
            product_number=p.product_line.product_number_snapshot,product_name=p.product_line.product_name_snapshot,
            specification=p.product_line.specification_snapshot,unit_name=p.unit_name_snapshot,
            order_quantity=progress[str(p.pk)]['required'],received_total=progress[str(p.pk)]['received'])
            for p in plans]
        return Response({'data':{'items':values,'total':total}})

    @extend_schema(request=AssemblyInput,responses={201:DataResponse,200:DataResponse})
    def create(self,request):
        data=read_data(AssemblyInput,request.data)
        receipt,replayed=confirm_assembly_receipt(request,data)
        return Response({'data':{'id':str(receipt.pk),'receipt_number':receipt.receipt_number,'replayed':replayed}},status=200 if replayed else 201)


class FinishedRecordViewSet(viewsets.ViewSet):
    permission_classes=[IsAuthenticated,HasActiveEmployee,BusinessActionPermission]
    serializer_class=DataResponse
    action_permission_map={key:'inventory.view_finishedgoodsreceipt' for key in ['list','retrieve','locations']}

    def list(self,request):
        data=read_data(Filters,request.query_params); rows=record_queryset()
        if data['q']:
            rows=rows.filter(Q(receipt_number__icontains=data['q'])|Q(task_number_snapshot__icontains=data['q'])|
                Q(order_number_snapshot__icontains=data['q'])|Q(product_number_snapshot__icontains=data['q'])|Q(product_name_snapshot__icontains=data['q']))
        if data['source']=='ASSEMBLY':rows=rows.filter(assembly_source__isnull=False)
        elif data['source']:rows=rows.filter(source_type=data['source'],assembly_source__isnull=True)
        for field,lookup in [('warehouse_id','location__zone__warehouse_id'),('zone_id','location__zone_id')]:
            if field in data:rows=rows.filter(**{lookup:data[field]})
        if 'schedule_product_id' in data:
            plan=get_object_or_404(schedule_items_for_category(request,'ASSEMBLY'),pk=data['schedule_product_id'])
            rows=rows.filter(production_task_product_id=plan.product_line_id)
        total=rows.count();start=(data['page']-1)*data['page_size']
        return Response({'data':{'items':[record_payload(r) for r in rows.order_by('-business_date','-received_at','-id')[start:start+data['page_size']]],'total':total}})

    def retrieve(self,request,pk=None):
        class Input(serializers.Serializer):
            id=serializers.UUIDField()
        data=read_data(Input,{'id':pk})
        return Response({'data':record_payload(get_object_or_404(record_queryset(),pk=data['id']))})

    @action(detail=False,methods=['get'])
    def locations(self,request):
        class Input(serializers.Serializer):
            product_id=serializers.UUIDField(required=False,allow_null=True)
            unit_id=serializers.UUIDField()
            zone_id=serializers.UUIDField()
            product_number=serializers.CharField(allow_blank=True,max_length=100)
            product_code=serializers.CharField(allow_blank=True,max_length=100)
            product_name=serializers.CharField(allow_blank=True,max_length=200)
            item_number=serializers.CharField(allow_blank=True,max_length=100)
            category=serializers.CharField(allow_blank=True,max_length=150)
            specification=serializers.CharField(allow_blank=True,max_length=300)
            actual_color=serializers.CharField(allow_blank=True,max_length=200)
        data=read_data(Input,request.query_params)
        filters={f'{key}_snapshot':data[key] for key in ['product_number','product_code','product_name','item_number','specification','category']}
        rows=FinishedGoodsReceipt.objects.filter(**filters,production_task_product__product_id=data.get('product_id'),
            unit_id=data['unit_id'],actual_color=data['actual_color'],location__zone_id=data['zone_id'],remaining_quantity__gt=0)
        locations=rows.values('location_id','location__location_number').annotate(quantity=Sum('remaining_quantity'),slots=Sum('remaining_box_slots'),
            unknown_packaging=Count('pk',filter=Q(remaining_box_slots__isnull=True))).order_by('location__location_number','location_id')
        return Response({'data':{'items':[{'location_id':str(r['location_id']),'location_number':r['location__location_number'],
            'quantity':r['quantity'],'slots':r['slots'],'unknown_packaging':r['unknown_packaging']} for r in locations]}})
