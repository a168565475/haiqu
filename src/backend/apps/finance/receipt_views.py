from django.http import FileResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access_control import module_policy
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from .receipt_models import FinanceReceiptUpload, Receipt, ReceiptAttachment
from .receipt_read_serializers import ReceiptDepositPageSerializer, ReceiptPageSerializer, ReceiptResponseSerializer, ReceiptSerializer, ReceiptUploadResponseSerializer, ReceiptUploadSerializer
from .receipt_selectors import receipts
from .receipt_serializers import ReceiptCreateSerializer, ReceiptDepositQuerySerializer, ReceiptQuerySerializer, ReceiptUploadInputSerializer, ReceiptUploadQuerySerializer, ReceiptVoidSerializer
from .receipt_uploads import create_receipt_upload, discard_receipt_upload, require_usable_file
from .selectors import available_cny_accounts
from .serializers import AccountQuerySerializer, AccountSerializer


def controlled_file_response(file, request):
    path = require_usable_file(file)
    try:
        stream = path.open("rb")
    except FileNotFoundError as exc:
        from .receipt_exceptions import ReceiptFileError
        raise ReceiptFileError("FILE_MISSING", "水单文件实体不存在。", status=404) from exc
    response = FileResponse(stream, content_type=file.content_type, as_attachment=request.query_params.get("download") == "true", filename=file.original_name)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


class ReceiptViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = ReceiptSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]
    action_permission_map = {"list": "finance.view_receipt", "retrieve": "finance.view_receipt",
        "create": "finance.add_receipt", "void": "finance.void_receipt", "attachment": "finance.view_receipt",
        "destroy": "finance.delete_receipt"}

    @extend_schema(responses={204: None}, parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    def destroy(self, request, pk=None):
        from .deletion_services import delete_receipt
        delete_receipt(request, pk)
        return Response(status=204)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return receipts().none()
        query = ReceiptQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return receipts(query.validated_data if self.action == "list" else {})

    def receipt_response(self, receipt, *, status=200, changed=None):
        current = receipts().get(pk=receipt.pk)
        data = dict(ReceiptSerializer(current).data)
        if changed is not None:
            data["changed"] = changed
        return Response({"data": data}, status=status, headers={"ETag": etag_for_instance(current)})

    @extend_schema(parameters=[ReceiptQuerySerializer], responses=ReceiptPageSerializer)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=ReceiptResponseSerializer)
    def retrieve(self, request, *args, **kwargs):
        return self.receipt_response(self.get_object())

    @extend_schema(request=ReceiptCreateSerializer, responses={200: ReceiptResponseSerializer, 201: ReceiptResponseSerializer},
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True),
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)])
    def create(self, request):
        from .receipt_services import create_receipt
        receipt, replayed = create_receipt(request)
        response = self.receipt_response(receipt, status=200 if replayed else 201)
        if replayed:
            response["Idempotent-Replayed"] = "true"
        return response

    @extend_schema(request=ReceiptVoidSerializer, responses=ReceiptResponseSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        from .receipt_services import void_receipt
        receipt, changed = void_receipt(request, pk)
        return self.receipt_response(receipt, changed=changed)

    @extend_schema(responses={(200, "image/png"): bytes})
    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<file_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
    def attachment(self, request, pk=None, file_id=None):
        receipt = self.get_object()
        attachment = ReceiptAttachment.objects.select_related("file").filter(receipt=receipt, file_id=file_id).first()
        if attachment is None and receipt.receipt_type == "GOODS":
            from .allocation_models import DepositAllocation
            deposit_ids = DepositAllocation.objects.filter(goods_receipt=receipt).values_list("deposit_receipt_id", flat=True)
            attachment = ReceiptAttachment.objects.select_related("file").filter(receipt_id__in=deposit_ids, file_id=file_id).first()
        if attachment is None:
            raise NotFound("水单不存在。")
        return controlled_file_response(attachment.file, request)


class ReceiptAccountOptionsViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = AccountSerializer
    http_method_names = ["get", "head", "options"]
    action_permission_map = {"list": "finance.add_receipt"}

    def check_permissions(self, request):
        super().check_permissions(request)
        if not all(module_policy.has_permission(request, code) for code in ("finance.add_receipt", "finance.view_financeaccount")):
            raise PermissionDenied("收款账户选择需要同时具备登记收款与查看公司账户权限。")

    def get_queryset(self):
        query = AccountQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        queryset = available_cny_accounts()
        if query.validated_data.get("q"):
            from django.db.models import Q
            term = query.validated_data["q"]
            queryset = queryset.filter(Q(code__icontains=term) | Q(name__icontains=term) | Q(account_number__icontains=term))
        return queryset

    @extend_schema(parameters=[AccountQuerySerializer])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class ReceiptUploadViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = ReceiptUploadSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]
    action_permission_map = {name: "finance.add_receipt" for name in ("list", "retrieve", "create", "destroy", "content")}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FinanceReceiptUpload.objects.none()
        return FinanceReceiptUpload.objects.select_related("file").filter(owner_employee=self.request.employee)

    @extend_schema(parameters=[ReceiptUploadQuerySerializer], responses=ReceiptUploadSerializer(many=True))
    def list(self, request):
        query = ReceiptUploadQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = self.get_queryset().filter(statement_id=query.validated_data["statement_id"], status__in=["UNBOUND", "DISCARD_PENDING"]).order_by("created_at", "id")
        return Response({"data": ReceiptUploadSerializer(rows, many=True).data})

    @extend_schema(responses=ReceiptUploadResponseSerializer)
    def retrieve(self, request, pk=None):
        return Response({"data": ReceiptUploadSerializer(self.get_object()).data})

    @extend_schema(request=ReceiptUploadInputSerializer, responses={201: ReceiptUploadResponseSerializer, 200: ReceiptUploadResponseSerializer})
    def create(self, request):
        serializer = ReceiptUploadInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        upload, replayed = create_receipt_upload(actor=request.employee, statement_id=data["statement_id"],
            upload_key=data["upload_key"], uploaded_file=data["file"], request=request)
        response = Response({"data": ReceiptUploadSerializer(upload).data}, status=200 if replayed else 201)
        if replayed:
            response["Idempotent-Replayed"] = "true"
        return response

    @extend_schema(responses=ReceiptUploadResponseSerializer)
    def destroy(self, request, pk=None):
        upload_id = serializers.UUIDField().run_validation(pk)
        upload = discard_receipt_upload(upload_id, actor=request.employee, request=request)
        return Response({"data": ReceiptUploadSerializer(upload).data})

    @extend_schema(responses={(200, "image/png"): bytes})
    @action(detail=True, methods=["get"])
    def content(self, request, pk=None):
        upload = self.get_object()
        if upload.status != "UNBOUND":
            raise NotFound("水单不可预览。")
        return controlled_file_response(upload.file, request)


class ReceiptStatementViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = ReceiptSerializer
    queryset = Receipt.objects.none()
    http_method_names = ["get", "head", "options"]
    action_permission_map = {"receipts": "finance.view_receipt", "available_deposits": "finance.add_receipt"}

    def get_statement(self, pk):
        from rest_framework.generics import get_object_or_404
        from .statement_models import ReceivableStatement
        return get_object_or_404(ReceivableStatement.objects.all(), pk=pk)

    @extend_schema(parameters=[ReceiptQuerySerializer], responses=ReceiptPageSerializer)
    def receipts(self, request, pk=None):
        statement = self.get_statement(pk)
        query = ReceiptQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = self.paginate_queryset(receipts({**query.validated_data, "statement_id": statement.pk}))
        return self.get_paginated_response(ReceiptSerializer(page, many=True).data)

    @extend_schema(parameters=[ReceiptDepositQuerySerializer], responses=ReceiptDepositPageSerializer)
    def available_deposits(self, request, pk=None):
        from .goods_selectors import deposit_option_data, deposit_options
        from .settlement_selectors import settlement_totals_for
        from .exceptions import FinanceConflict
        statement = self.get_statement(pk)
        if statement.status != "ACTIVE":
            raise FinanceConflict("STATEMENT_VOID", "对账单已作废，不能选择订金。")
        query = ReceiptDepositQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        totals = settlement_totals_for(statement)
        rows = deposit_options(statement, include_unavailable=query.validated_data["include_unavailable"])
        if query.validated_data.get("q"):
            rows = rows.filter(number__icontains=query.validated_data["q"])
        page = self.paginate_queryset(rows)
        response = self.get_paginated_response([deposit_option_data(item, totals) for item in page])
        response.data["outstanding_amount"] = str(totals.outstanding_amount)
        response.data["available_deposit_amount"] = str(totals.available_deposit_amount)
        response.data["statement_etag"] = etag_for_instance(statement)
        return response
