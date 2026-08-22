from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.customers.api.views import CustomerApiViewSetBase

from ..models import SavedView
from .serializers import SavedViewArchiveSerializer, SavedViewSerializer


class SavedViewViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, CustomerApiViewSetBase
):
    serializer_class = SavedViewSerializer
    action_permission_map = {
        "list": "preferences.view_savedview", "retrieve": "preferences.view_savedview",
        "create": "preferences.add_savedview", "partial_update": "preferences.change_savedview",
        "set_default": "preferences.change_savedview", "archive": "preferences.change_savedview",
    }

    def _employee(self):
        employee = self.actor_employee()
        if employee is None:
            raise PermissionDenied("保存视图必须绑定到有效员工档案。")
        return employee

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SavedView.objects.none()
        queryset = SavedView.objects.filter(employee=self._employee())
        archived = self.request.query_params.get("archived", "false").lower()
        if archived == "true":
            queryset = queryset.filter(archived_at__isnull=False)
        elif archived != "all":
            queryset = queryset.filter(archived_at__isnull=True)
        module_code = self.request.query_params.get("module_code")
        if module_code:
            queryset = queryset.filter(module_code=module_code.upper())
        return queryset.order_by("module_code", "sort_order", "view_name", "id")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            saved_view = serializer.save(employee=self._employee())
        except IntegrityError as exc:
            raise Conflict("同一模块已存在同名的有效保存视图。") from exc
        return self.response_with_etag({"data": SavedViewSerializer(saved_view).data}, saved_view, status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        saved_view = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(saved_view).data}, saved_view)

    def partial_update(self, request, *args, **kwargs):
        saved_view = self.get_object()
        require_matching_etag(request, saved_view)
        serializer = self.get_serializer(saved_view, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data:
            raise ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        try:
            with transaction.atomic():
                saved_view = SavedView.objects.select_for_update().get(pk=saved_view.pk)
                require_matching_etag(request, saved_view)
                saved_view = SavedViewSerializer(saved_view, data=request.data, partial=True)
                saved_view.is_valid(raise_exception=True)
                saved_view = saved_view.save()
        except IntegrityError as exc:
            raise Conflict("同一模块已存在同名的有效保存视图。") from exc
        return self.response_with_etag({"data": SavedViewSerializer(saved_view).data}, saved_view)

    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        saved_view = self.get_object()
        require_matching_etag(request, saved_view)
        with transaction.atomic():
            saved_view = SavedView.objects.select_for_update().get(pk=saved_view.pk)
            require_matching_etag(request, saved_view)
            if saved_view.archived_at is not None:
                raise Conflict("已归档视图不能设为默认。")
            SavedView.objects.filter(
                employee=saved_view.employee, module_code=saved_view.module_code,
                archived_at__isnull=True, is_default=True,
            ).exclude(pk=saved_view.pk).update(is_default=False, updated_at=timezone.now())
            saved_view.is_default = True
            saved_view.save(update_fields=["is_default", "updated_at"])
        return self.response_with_etag({"data": SavedViewSerializer(saved_view).data}, saved_view)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        saved_view = self.get_object()
        require_matching_etag(request, saved_view)
        serializer = SavedViewArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            saved_view = SavedView.objects.select_for_update().get(pk=saved_view.pk)
            require_matching_etag(request, saved_view)
            if saved_view.archived_at is not None:
                raise Conflict("保存视图已经归档。")
            saved_view.archived_at = timezone.now()
            saved_view.archived_by_employee = self._employee()
            saved_view.archive_reason = serializer.validated_data["reason"]
            saved_view.is_default = False
            saved_view.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "is_default", "updated_at"])
        return self.response_with_etag({"data": SavedViewSerializer(saved_view).data}, saved_view)
