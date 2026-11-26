from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from apps.access_control import module_policy
from apps.access_control.module_operations import CUT_PIECE_PRINTING
from apps.core.api.permissions import HasActiveEmployee
from apps.production_tasks.selectors import production_task_product_image

from ..models import TubeOutsourcingAction, TubeOutsourcingOrder
from ..tube_selectors import (CANCEL_PERMISSION, CREATE_PERMISSION, DISPATCH_PERMISSION, RETURN_PERMISSION, VIEW_PERMISSION,
    product_display, product_summary, require_saved_order_access, require_tube_feature, saved_order_data, source_factories,
    source_product, source_zone, tube_options, tube_order_queryset, visible_products)
from ..tube_services import create_tube_order
from ..tube_action_services import confirm_tube_action
from ..tube_receipt_services import confirm_tube_final_receipt
from ..tube_receipt_selectors import (receipt_candidates, receipt_data, receipt_preview,
                                     receipt_queryset, require_receipt_read_access)
from ..tube_kinds import CUTTING_SOURCES, source_category, output_unit
from ..warehouse_access import warehouse_read_permission, warehouse_stage, warehouse_tube_orders
from .print_pdf import PRINT_KIND_PARAMETER, PRINT_PDF_RESPONSES, PRINT_WAREHOUSE_PARAMETER, print_kind, print_pdf_response
from .tube_serializers import (TubeCancelWriteSerializer, TubeDispatchWriteSerializer,
    TubeOrderWriteSerializer, TubeSourceQuerySerializer, TubeReceiptCandidatesQuerySerializer,
    TubeReceiptWriteSerializer, TubeReceiptResponseSerializer, TubeReceiptPreviewResponseSerializer,
    TubeReceiptCandidatesResponseSerializer)
from .tube_serializers import TubePlanDispatchSerializer, TubePlanRecordCorrectionSerializer, TubePlanQuantityWriteSerializer


class TubeActionPermission(BasePermission):
    message = '当前账号没有执行外发单操作的权限。'

    def has_permission(self, request, view):
        if view.printing:
            return module_policy.has_permission(request, CUT_PIECE_PRINTING)
        warehouse_allowed = warehouse_read_permission(request, view)
        if warehouse_allowed is not None:
            return warehouse_allowed
        permission = view.action_permission_map.get(view.action)
        permissions = permission if isinstance(permission, tuple) else (permission,)
        return any(value and module_policy.has_permission(request, value) for value in permissions)


class TubeOutsourcingOrderViewSet(viewsets.GenericViewSet):
    printing = False
    write_serializer = TubeOrderWriteSerializer
    permission_classes = [HasActiveEmployee, TubeActionPermission]
    warehouse_read_actions = {'retrieve', 'print_pdf', 'action_by_request', 'receipt_preview', 'receipt'}
    warehouse_read_permissions = (DISPATCH_PERMISSION, RETURN_PERMISSION)
    action_permission_map = {'options': VIEW_PERMISSION, 'source_context': (VIEW_PERMISSION, DISPATCH_PERMISSION), 'product_image': VIEW_PERMISSION,
                             'create': CREATE_PERMISSION, 'by_request': VIEW_PERMISSION,
                             'retrieve': VIEW_PERMISSION, 'print_pdf': VIEW_PERMISSION, 'confirm_dispatch': DISPATCH_PERMISSION,
                             'cancel': CANCEL_PERMISSION, 'action_by_request': VIEW_PERMISSION,
                             'receipt_candidates': RETURN_PERMISSION, 'receipt_preview': (VIEW_PERMISSION, RETURN_PERMISSION),
                             'confirm_receipt': RETURN_PERMISSION, 'receipt_by_request': RETURN_PERMISSION,
                             'receipt': (VIEW_PERMISSION, RETURN_PERMISSION),
                             'plan_dispatch': DISPATCH_PERMISSION, 'plan_receipt': RETURN_PERMISSION,
                             'plan_quantity': 'outsourcing.change_outsourcingorder',
                             'plan_record_correction': (DISPATCH_PERMISSION, RETURN_PERMISSION),
                             'plan_record_correction_by_request': (DISPATCH_PERMISSION, RETURN_PERMISSION)}

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        require_tube_feature()

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('category', str, location=OpenApiParameter.QUERY, enum=['tube', 'cutting'], default='tube')])
    @action(detail=False, methods=['get'])
    def options(self, request):
        if self.printing:
            return Response({'data': tube_options(request, category='screen_printing', permission=CUT_PIECE_PRINTING)})
        return Response({'data': tube_options(request, category=request.query_params.get('category', 'tube'))})

    @extend_schema(request=None, parameters=[
        OpenApiParameter('schedule_product_id', OpenApiTypes.UUID, location=OpenApiParameter.PATH),
        OpenApiParameter('file_id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)],
        responses={(200, 'application/octet-stream'): OpenApiTypes.BINARY})
    @action(detail=False, methods=['get'],
        url_path=r'product-images/(?P<schedule_product_id>[^/.]+)/(?P<file_id>[^/.]+)')
    def product_image(self, request, schedule_product_id=None, file_id=None, product_line_id=None):
        file_id = serializers.UUIDField().run_validation(file_id)
        if self.printing and product_line_id is not None:
            from ..tube_selectors import printing_product_lines
            line = get_object_or_404(printing_product_lines(request), pk=product_line_id)
        else:
            schedule_product_id = serializers.UUIDField().run_validation(schedule_product_id)
            permission = CUT_PIECE_PRINTING if self.printing else VIEW_PERMISSION
            line = get_object_or_404(visible_products(request, permission, category='all'), pk=schedule_product_id).product_line
        # 图片读取只继承当前外发产品的可见范围，不能转为整张任务或通用文件权限。
        image = production_task_product_image(line)
        if image is None or image.pk != file_id or not image.content_type.startswith('image/'):
            raise Http404('产品图片不存在。')
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_path = (media_root / image.storage_key).resolve()
        try:
            storage_path.relative_to(media_root)
        except ValueError as exc:
            raise Http404('图片路径无效。') from exc
        if not storage_path.is_file():
            raise Http404('图片不存在。')
        response = FileResponse(storage_path.open('rb'), content_type=image.content_type, filename=image.original_name)
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response

    @extend_schema(request=None, parameters=[TubeSourceQuerySerializer], responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=['get'], url_path='source-context')
    def source_context(self, request):
        serializer = TubeSourceQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data['source_kind'] == 'PROCESSOR' and (not data.get('plan_id') or data.get('is_plan')):
            raise serializers.ValidationError('加工点发出须从仓库已保存的车缝总单办理。')
        permission = DISPATCH_PERMISSION if data.get('plan_id') else VIEW_PERMISSION
        plan = None
        if data.get('plan_id'):
            identifiers = {key: data[key] for key in ('product_line_id', 'schedule_product_id') if key in data}
            plan = get_object_or_404(TubeOutsourcingOrder, pk=data['plan_id'], is_plan=True, **identifiers)
            require_saved_order_access(request, plan, permission)
        saved_printing = plan is not None and plan.source_snapshot.get('screen_print_pieces')
        if saved_printing:
            product, craft = plan.schedule_product, plan.craft
            if data.get('craft_id') != plan.craft_id:
                raise Http404('所选工艺与丝印总单不符。')
        else:
            if not data.get('schedule_product_id'):
                raise serializers.ValidationError({'schedule_product_id': '请选择已排产的产品。'})
            product, craft = source_product(request, data['schedule_product_id'], permission,
                source_kind=data['source_kind'], craft_id=data.get('craft_id'))
        if data.get('category') == 'cutting' and craft.outsourcing_code == 'SEWING':
            # 沿用已有单据的加工分类；实际发料来源仍由后续发货单独选择。
            from apps.boms.models import BomLine
            if BomLine.objects.filter(section__bom__product_line_id=product.product_line_id,
                    section__bom__archived_at__isnull=True, component_kind='SEWN_PART').exists():
                data['source_kind'] = 'CUTTING'
        if plan is not None:
            if plan.craft_id != craft.pk:
                raise Http404('所选工艺与委外总单不符。')
            if data['source_kind'] == 'PROCESSOR' and not (plan.craft.outsourcing_code == 'SEWING'
                    and plan.source_snapshot.get('sewing_inputs')):
                raise serializers.ValidationError('加工点发出只适用于以裁片为投入的车缝总单。')
        zone = source_zone(data['source_kind'], data.get('zone_id'))
        from apps.inventory.tube_outsourcing_limits import tube_source_context
        from ..tube_materials import tube_material_context
        if saved_printing:
            from ..part_flow_services import printing_dispatch_context
            context = printing_dispatch_context(plan, data['source_kind'], zone, request)
        elif data.get('is_plan') or data.get('plan_id'):
            from ..plan_services import plan_source_context
            context = plan_source_context(schedule_product=product, source_kind=data['source_kind'],
                zone=zone, craft=craft, for_plan=bool(data.get('is_plan')), request=request)
            if data.get('plan_id'):
                if bool(plan.source_snapshot.get('screen_print_pieces')) != bool(context.get('screen_print_pieces')):
                    raise serializers.ValidationError('该发料来源与委外总单记录的工艺不符。')
            elif context.get('screen_print_pieces'):
                raise serializers.ValidationError('请选择对应的委外建单入口。')
            if data.get('plan_id') and data['source_kind'] == 'CUTTING' and context.get('sewing_inputs'):
                from ..part_flow_sources import add_cut_piece_stock_zones
                from ..source_access import allowed_source_kinds
                if 'PUBLIC_PIECE' in allowed_source_kinds(request, permission):
                    add_cut_piece_stock_zones(product, plan, context['inputs'])
        elif data['source_kind'] in CUTTING_SOURCES:
            from ..cutting_sources import cutting_source_context
            context = cutting_source_context(schedule_product=product, source_kind=data['source_kind'], zone=zone, craft=craft)
        else:
            context = tube_source_context(schedule_product=product, source_kind=data['source_kind'], zone=zone)
        options = tube_options(request, permission=permission, category='screen_printing' if self.printing
                               else source_category(data['source_kind'])) if not data.get('plan_id') else {}
        skip_materials = context.get('screen_print_pieces') or (data.get('is_plan') and craft.outsourcing_code == 'SEWING')
        materials = {'material_rows': []} if skip_materials else tube_material_context(product, source_kind=data['source_kind'],
                       plan_mode=bool(data.get('is_plan') or data.get('plan_id')), for_plan=bool(data.get('is_plan')))
        line = plan.product_line if plan else product.product_line
        context = {**context, **product_summary(product, product_line=line), **product_display(product, printing=bool(self.printing or saved_printing), product_line=line), **materials,
                   **options, 'craft_name': craft.name, 'craft_id': str(craft.pk),
                   'output_unit': output_unit(data['source_kind']),
                   'material_category': '辅料' if data['source_kind'] in CUTTING_SOURCES else '五金',
                   'source_kind': data['source_kind'], 'zone_id': str(zone.pk) if zone else None,
                   'factories': [{'id': str(factory.pk), 'name': factory.name} for factory in source_factories(request, craft, permission)]}
        # 库存身份和冻结凭证仅供保存服务使用，页面按可显示字段读取。
        context['rows'] = [{key: value for key, value in row.items() if key not in {'input_identity', 'snapshot'}}
                           for row in context.get('rows', [])]
        context['inputs'] = [{key: value for key, value in row.items() if key not in {'input_identity', 'snapshot'}}
                             for row in context.get('inputs', [])]
        if context.get('part_flow'):
            if data.get('is_plan') and context.get('sewing_inputs'):
                from ..sewing_assignments import internal_sewing_factory_id
                own_id = internal_sewing_factory_id()
                context['internal_sewing_factory_id'] = str(own_id) if own_id else None
            if data.get('plan_id') and 'sewing_part_assignments' in plan.source_snapshot:
                external = {str(value) for value in plan.lines.values_list('component_identity', flat=True)}
                context['rows'] = [row for row in context['rows'] if row['component_identity'] in external]
                context['inputs'] = [row for row in context['inputs'] if row['parent_component_identity'] in external]
                own_id = plan.source_snapshot['sewing_part_assignments'].get('internal_factory_id')
                context['factories'] = [row for row in context['factories'] if row['id'] != own_id]
            units = {row['unit'] for row in context['rows']}
            context['output_unit'] = next(iter(units)) if len(units) == 1 else ''
        if data.get('is_plan') and not self.printing:
            from ..plan_purchase_reference import add_plan_purchase_reference
            add_plan_purchase_reference(context, line)
        return Response({'data': context})

    @extend_schema(request=TubeOrderWriteSerializer, responses={200: OpenApiTypes.OBJECT, 201: OpenApiTypes.OBJECT})
    def create(self, request):
        serializer = self.write_serializer(data=request.data, context={'cut_piece_printing': self.printing})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if self.printing:
            if not data.get('is_plan') or data.get('source_kind') != 'CUTTING':
                raise serializers.ValidationError('跟单入口仅支持裁片丝印总单。')
            from ..plan_services import create_plan
            order, created = create_plan(data=data, request=request, permission=CUT_PIECE_PRINTING)
        else:
            order, created = create_tube_order(data=data, request=request)
        order = tube_order_queryset().get(pk=order.pk)
        data = saved_order_data(order, created=created, request=request)
        response = Response({'data': data}, status=201 if created else 200)
        response['ETag'] = data['etag']
        return response

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('request_id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=False, methods=['get'], url_path=r'by-request/(?P<request_id>[^/.]+)')
    def by_request(self, request, request_id=None):
        request_id = serializers.UUIDField().run_validation(request_id)
        order = get_object_or_404(tube_order_queryset(), client_request_id=request_id)
        require_saved_order_access(request, order, CUT_PIECE_PRINTING if self.printing else VIEW_PERMISSION)
        data = saved_order_data(order, request=request)
        response = Response({'data': data})
        response['ETag'] = data['etag']
        return response

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    def retrieve(self, request, pk=None):
        order = self._get_detail_order(request, pk)
        return self._detail_response(order, request)

    @extend_schema(responses=PRINT_PDF_RESPONSES, parameters=[
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH),
        PRINT_KIND_PARAMETER, PRINT_WAREHOUSE_PARAMETER])
    @action(detail=True, methods=['get'], url_path='print-pdf')
    def print_pdf(self, request, pk=None):
        order = self._get_detail_order(request, pk)
        kind = print_kind(request, spray_allowed=order.source_kind in {'RAW_PIPE', 'PUBLIC_SEMI', 'METAL'})
        detail = saved_order_data(order, include_metal_basis=False)
        return print_pdf_response(detail, kind=kind, tube=True)

    def _get_detail_order(self, request, pk):
        pk = serializers.UUIDField().run_validation(pk)
        order = get_object_or_404(tube_order_queryset(), pk=pk)
        self._require_detail_access(request, order)
        return order

    def _require_detail_access(self, request, order):
        if self.printing:
            require_saved_order_access(request, order, CUT_PIECE_PRINTING)
        elif warehouse_stage(request):
            get_object_or_404(warehouse_tube_orders(request), pk=order.pk)
        else:
            require_saved_order_access(request, order)

    def _detail_response(self, order, request, *, action_record=None, created=False):
        data = saved_order_data(order, request=request, action_record=action_record, created=created)
        response = Response({'data': data})
        response['ETag'] = data['etag']
        return response

    @extend_schema(request=TubePlanQuantityWriteSerializer, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('If-Match', str, location=OpenApiParameter.HEADER, required=True),
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['patch'], url_path='plan-quantity')
    def plan_quantity(self, request, pk=None):
        from ..plan_services import update_plan_quantity
        pk = serializers.UUIDField().run_validation(pk)
        serializer = TubePlanQuantityWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = update_plan_quantity(order_id=pk, data=serializer.validated_data, request=request)
        return self._detail_response(tube_order_queryset().get(pk=order.pk), request)

    @extend_schema(request=TubeDispatchWriteSerializer, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('If-Match', str, location=OpenApiParameter.HEADER, required=True),
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['post'], url_path='dispatch')
    def confirm_dispatch(self, request, pk=None):
        return self._confirm_action(request, pk, 'DISPATCH', TubeDispatchWriteSerializer)

    @extend_schema(request=TubeCancelWriteSerializer, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('If-Match', str, location=OpenApiParameter.HEADER, required=True),
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        return self._confirm_action(request, pk, 'CANCEL', TubeCancelWriteSerializer)

    def _confirm_action(self, request, pk, kind, serializer_class):
        pk = serializers.UUIDField().run_validation(pk)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        order, record, created = confirm_tube_action(order_id=pk, kind=kind,
            data=serializer.validated_data, request=request)
        order = tube_order_queryset().get(pk=order.pk)
        return self._detail_response(order, request, action_record=record, created=created)

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH),
        OpenApiParameter('request_id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['get'], url_path=r'action-by-request/(?P<request_id>[^/.]+)')
    def action_by_request(self, request, pk=None, request_id=None):
        pk = serializers.UUIDField().run_validation(pk)
        request_id = serializers.UUIDField().run_validation(request_id)
        order = get_object_or_404(tube_order_queryset(), pk=pk)
        self._require_detail_access(request, order)
        record = get_object_or_404(TubeOutsourcingAction.objects.select_related('actor_employee'),
                                   order_id=order.pk, client_request_id=request_id)
        return self._detail_response(order, request, action_record=record)

    @extend_schema(request=None, parameters=[TubeReceiptCandidatesQuerySerializer], responses=TubeReceiptCandidatesResponseSerializer)
    @action(detail=False, methods=['get'], url_path='receipt-candidates')
    def receipt_candidates(self, request):
        serializer = TubeReceiptCandidatesQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return Response({'data': receipt_candidates(request, serializer.validated_data)})

    @extend_schema(request=None, responses=TubeReceiptPreviewResponseSerializer,
        parameters=[OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['get'], url_path='receipt-preview')
    def receipt_preview(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        order = get_object_or_404(tube_order_queryset(), pk=pk)
        data = receipt_preview(order, request)
        response = Response({'data': data})
        response['ETag'] = data['etag']
        return response

    @extend_schema(request=TubeReceiptWriteSerializer, responses={200: TubeReceiptResponseSerializer,
        201: TubeReceiptResponseSerializer}, parameters=[OpenApiParameter('If-Match', str,
        location=OpenApiParameter.HEADER, required=True),
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['post'], url_path='confirm-receipt')
    def confirm_receipt(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        serializer = TubeReceiptWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record, created = confirm_tube_final_receipt(order_id=pk, data=serializer.validated_data, request=request)
        return self._receipt_response(receipt_queryset().get(pk=record.pk), created=created)

    def _receipt_response(self, record, *, created=False):
        data = receipt_data(record, created=created)
        response = Response({'data': data}, status=201 if created else 200)
        response['ETag'] = data['etag']
        return response

    @extend_schema(request=None, responses=TubeReceiptResponseSerializer, parameters=[
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH),
        OpenApiParameter('request_id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['get'], url_path=r'receipt-by-request/(?P<request_id>[^/.]+)')
    def receipt_by_request(self, request, pk=None, request_id=None):
        pk = serializers.UUIDField().run_validation(pk)
        request_id = serializers.UUIDField().run_validation(request_id)
        record = get_object_or_404(receipt_queryset(), order_id=pk, client_request_id=request_id)
        require_saved_order_access(request, record.order, RETURN_PERMISSION)
        return self._receipt_response(record)

    @extend_schema(request=None, responses=TubeReceiptResponseSerializer,
        parameters=[OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['get'], url_path='receipt')
    def receipt(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        record = get_object_or_404(receipt_queryset(), order_id=pk)
        require_receipt_read_access(request, record.order)
        return self._receipt_response(record)

    @extend_schema(request=TubePlanDispatchSerializer, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('If-Match', str, location=OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=['post'], url_path='plan-dispatch')
    def plan_dispatch(self, request, pk=None):
        from ..plan_services import dispatch_plan
        return self._plan_write(request, pk, TubePlanDispatchSerializer, dispatch_plan)

    @extend_schema(request=TubeReceiptWriteSerializer, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('If-Match', str, location=OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=['post'], url_path='plan-receipt')
    def plan_receipt(self, request, pk=None):
        from ..plan_services import receive_plan
        return self._plan_write(request, pk, TubeReceiptWriteSerializer, receive_plan)

    @extend_schema(request=TubePlanRecordCorrectionSerializer, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('If-Match', str, location=OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=['post'], url_path='plan-record-correction')
    def plan_record_correction(self, request, pk=None):
        from ..plan_correction_services import correct_plan_record
        pk = serializers.UUIDField().run_validation(pk)
        serializer = TubePlanRecordCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order, correction, _ = correct_plan_record(order_id=pk, data=serializer.validated_data, request=request)
        return self._correction_response(order.pk, correction, request)

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter('request_id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['get'], url_path=r'plan-record-correction-by-request/(?P<request_id>[^/.]+)')
    def plan_record_correction_by_request(self, request, pk=None, request_id=None):
        from ..plan_correction_services import find_record_correction
        pk = serializers.UUIDField().run_validation(pk)
        request_id = serializers.UUIDField().run_validation(request_id)
        correction = find_record_correction(order_id=pk, request_id=request_id, request=request)
        return self._correction_response(pk, correction, request)

    def _correction_response(self, order_id, correction, request):
        from ..plan_correction_services import correction_data
        data = saved_order_data(tube_order_queryset().get(pk=order_id), request=request)
        data['record_correction'] = correction_data(correction)
        response = Response({'data': data})
        response['ETag'] = data['etag']
        return response

    def _plan_write(self, request, pk, serializer_class, service):
        pk = serializers.UUIDField().run_validation(pk)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        order, created = service(order_id=pk, data=serializer.validated_data, request=request)
        return self._detail_response(tube_order_queryset().get(pk=order.pk), request, created=created)
