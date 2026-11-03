from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.access_control.module_policy import has_permission
from apps.core.api.permissions import HasActiveEmployee
from apps.core.api.exceptions import Conflict

from .finished_receipts import FINISHED_RECEIPT_ADD, finished_receipt_options, finished_receipt_products
from .semi_receipts import SEMI_RECEIPT_ADD, SEMI_RECEIPT_VIEW
from .selectors import ISSUE_VIEW, REPORT_VIEW, filtered_plan_keys, mobile_plan_data, mobile_workshop_filter
from .serializers import (MobileContextResponseSerializer, MobileFinishedReceiptOptionsResponseSerializer,
                         MobileFinishedReceiptQuerySerializer, MobilePlanDetailQuerySerializer, MobilePlanQuerySerializer)


def require_mobile_access(request):
    if any(has_permission(request, code) for code in (ISSUE_VIEW, REPORT_VIEW, FINISHED_RECEIPT_ADD)):
        return
    if has_permission(request, SEMI_RECEIPT_VIEW) and has_permission(request, SEMI_RECEIPT_ADD):
        return
    raise PermissionDenied("当前账号没有领料、报工查看或入库操作权限。")


class MobileFinishedReceiptOptionsView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_mobile_finished_receipt_options",
                   parameters=[MobileFinishedReceiptQuerySerializer], responses=MobileFinishedReceiptOptionsResponseSerializer)
    def get(self, request):
        if not has_permission(request, FINISHED_RECEIPT_ADD):
            raise PermissionDenied("当前账号没有成品入库权限。")
        query = MobileFinishedReceiptQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        plan = get_object_or_404(finished_receipt_products(request), pk=query.validated_data['schedule_product_id'])
        if plan.schedule.production_task.status != 'IN_PRODUCTION':
            raise Conflict("只有生产中的订单产品可以办理成品入库。")
        return Response({'data': finished_receipt_options()})


class MobileContextView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_mobile_context", responses=MobileContextResponseSerializer)
    def get(self, request):
        require_mobile_access(request)
        return Response(MobileContextResponseSerializer({
            "data": {"workshop_filter": mobile_workshop_filter(request)},
        }).data)


class MobilePlanListView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_mobile_plan_list", parameters=[MobilePlanQuerySerializer], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        require_mobile_access(request)
        query = MobilePlanQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = list(self.paginate_queryset(filtered_plan_keys(request, query.validated_data)))
        return self.get_paginated_response(mobile_plan_data(request, page, production_date=query.validated_data.get("production_date")))


class MobilePlanDetailView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_mobile_plan_detail", parameters=[MobilePlanDetailQuerySerializer], responses=OpenApiTypes.OBJECT)
    def get(self, request, schedule_product_id):
        require_mobile_access(request)
        query = MobilePlanDetailQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        key = get_object_or_404(filtered_plan_keys(request, query.validated_data), schedule_product_id=schedule_product_id)
        rows = mobile_plan_data(request, [key], production_date=query.validated_data.get("production_date"), include_people=True)
        if not rows:
            raise Http404("生产计划不存在或已不可访问。")
        return Response({"data": rows[0]})
