from io import BytesIO

from django.http import HttpResponse
from openpyxl import Workbook
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.customers.api.views import CustomerApiViewSetBase
from apps.customers.selectors import accessible_customers

from ..contact_import import CONTACT_COLUMNS, process_contact_import
from ..models import ImportBatch
from ..security import save_and_scan_upload
from .serializers import ContactImportBatchSerializer, ContactImportUploadSerializer, ImportRecordSerializer


class ContactImportViewSet(mixins.RetrieveModelMixin, CustomerApiViewSetBase):
    serializer_class = ContactImportBatchSerializer
    parser_classes = [MultiPartParser, FormParser]
    action_permission_map = {
        "create": "customers.import_customercontact",
        "retrieve": "customers.import_customercontact",
        "template": "customers.import_customercontact",
        "records": "customers.import_customercontact",
    }

    def get_queryset(self):
        queryset = ImportBatch.objects.filter(import_type="CONTACT").select_related("source_file")
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(created_by_employee=self.actor_employee())

    def create(self, request, *args, **kwargs):
        serializer = ContactImportUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        business_file, path = save_and_scan_upload(
            serializer.validated_data["file"],
            self.actor_employee(),
        )
        batch = process_contact_import(
            business_file=business_file,
            path=path,
            actor_employee=self.actor_employee(),
            request=request,
            accessible_customers=accessible_customers(request, "import_customercontact"),
            customer_id=serializer.validated_data.get("customer_id"),
            allow_duplicates=serializer.validated_data["allow_same_customer_duplicates"],
        )
        return Response(
            {"data": ContactImportBatchSerializer(batch).data},
            status=status.HTTP_201_CREATED,
        )

    def retrieve(self, request, *args, **kwargs):
        return Response({"data": self.get_serializer(self.get_object()).data})

    @action(detail=False, methods=["get"])
    def template(self, request):
        scope = request.query_params.get("scope", "global")
        if scope not in {"global", "customer"}:
            return Response({"scope": ["scope 只能是 global 或 customer。"]}, status=400)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "联系人导入"
        sheet.append(CONTACT_COLUMNS)
        sheet.append([
            "CUS-0001" if scope == "global" else "", "张三", "采购经理", "ACTIVE", "是",
            "zhangsan@example.com", "13800138000", "", "zhangsan", "", "BUYER|DECISION_MAKER", "示例行，请删除后导入",
        ])
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="contact_import_template.xlsx"'
        return response

    @action(detail=True, methods=["get"])
    def records(self, request, pk=None):
        batch = self.get_object()
        queryset = batch.records.order_by("row_number", "id")
        page = self.paginate_queryset(queryset)
        serializer = ImportRecordSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)
