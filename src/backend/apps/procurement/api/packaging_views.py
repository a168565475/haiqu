from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.boms.models import BomLine

from ..models import PurchaseScope, SupplierCategory
from ..packaging_purchase import get_packaging_page, packaging_page_etag, prepare_packaging_groups, process_packaging_page
from ..purchase_scope import PACKAGING_PERMISSION, packaging_bom_lines
from ..selectors import production_tasks_with_purchase_sources
from ..services import PURCHASABLE_TASK_STATUSES, evaluate_purchase_source
from .group_serializers import PurchaseGroupSerializer
from .group_views import PurchaseGroupRecordViewSet
from .packaging_serializers import (
    PackagingPageConfirmSerializer, PackagingPageReadSerializer, PackagingPageSaveSerializer,
    PackagingPrepareSerializer, PackagingSourceSerializer,
)
from .views import purchase_form_options


PACKAGING_ACTIONS = dict.fromkeys((
    "list", "retrieve", "filter_options", "complete", "destroy",
    "sources", "options", "prepare", "batch_page", "save_page", "confirm_page",
), PACKAGING_PERMISSION)

group_response = inline_serializer(
    name="PackagingPurchaseGroupsResponse", fields={"data": PurchaseGroupSerializer(many=True)},
)
if_match = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


class PackagingPurchaseGroupViewSet(PurchaseGroupRecordViewSet):
    purchase_scope = PurchaseScope.PACKAGING
    action_permission_map = PACKAGING_ACTIONS

    def _tasks(self):
        from ..source_access import packaging_purchase_tasks
        return packaging_purchase_tasks(self.request)

    def _task_ids(self):
        return self._tasks().order_by().values_list("pk", flat=True)

    @extend_schema(responses=inline_serializer(
        name="PackagingPurchaseSourcesResponse", fields={"data": PackagingSourceSerializer(many=True)},
    ))
    @action(detail=False, methods=["get"])
    def sources(self, request):
        candidates = packaging_bom_lines(BomLine.objects.filter(
            section__bom__archived_at__isnull=True,
        )).order_by().values("section__bom__production_task_id")
        tasks = production_tasks_with_purchase_sources(
            self._tasks().filter(status__in=PURCHASABLE_TASK_STATUSES, pk__in=candidates).order_by("-updated_at", "pk"),
        )
        rows = []
        for task in tasks:
            for option in evaluate_purchase_source(task, purchase_scope=PurchaseScope.PACKAGING)["bom_options"]:
                revision = option.get("combine_source_revision") or option.get("source_revision")
                if revision or option.get("existing_purchase_group_id"):
                    if not revision:
                        from ..models import PurchaseGroupBomSource
                        revision = PurchaseGroupBomSource.objects.filter(
                            purchase_group_id=option["existing_purchase_group_id"], product_line_id_snapshot=option["product_line_id"],
                        ).values_list("source_revision", flat=True).first()
                    if option["bom_id"] and revision:
                        rows.append({**option, "source_revision": revision,
                                     "production_task_id": task.pk, "task_number": task.task_number})
        return Response({"data": PackagingSourceSerializer(rows, many=True).data})

    @action(detail=False, methods=["get"])
    def options(self, request):
        options = purchase_form_options()
        options["suppliers"] = [
            supplier for supplier in options["suppliers"] if SupplierCategory.PACKAGING in supplier["supplier_categories"]
        ]
        return Response({"data": options})

    @extend_schema(request=PackagingPrepareSerializer, responses=group_response)
    @action(detail=False, methods=["post"])
    def prepare(self, request):
        serializer = PackagingPrepareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        groups = prepare_packaging_groups(serializer.validated_data["sources"], self._tasks(), request)
        return Response({"data": PurchaseGroupSerializer(groups, many=True).data})

    @extend_schema(parameters=[PackagingPageReadSerializer], responses=group_response)
    @action(detail=False, methods=["get"], url_path="batch-page")
    def batch_page(self, request):
        serializer = PackagingPageReadSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return self._page_response(
            get_packaging_page(self._accessible_groups(), **serializer.validated_data),
            serializer.validated_data,
        )

    @extend_schema(request=PackagingPageSaveSerializer, parameters=[if_match], responses=group_response)
    @action(detail=False, methods=["post"], url_path="save-page")
    def save_page(self, request):
        return self._write_page(PackagingPageSaveSerializer, confirm=False)

    @extend_schema(request=PackagingPageConfirmSerializer, parameters=[if_match], responses=group_response)
    @action(detail=False, methods=["post"], url_path="confirm-page")
    def confirm_page(self, request):
        return self._write_page(PackagingPageConfirmSerializer, confirm=True)

    def _write_page(self, serializer_class, *, confirm):
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        groups = process_packaging_page(
            allowed_groups=self._accessible_groups(), allowed_task_ids=self._task_ids(),
            data=serializer.validated_data, request=self.request, confirm=confirm,
        )
        return self._page_response(groups, serializer.validated_data)

    @staticmethod
    def _page_response(groups, data):
        response = Response({
            "data": PurchaseGroupSerializer(groups, many=True, context={"batch_session_id": data["batch_session_id"]}).data,
        })
        response["ETag"] = packaging_page_etag(groups)
        return response
