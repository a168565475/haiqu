from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import Case, Count, IntegerField, Q, Value, When
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.organizations.models import Employee
from apps.organizations.selectors import active_department_employees

from ..constants import FIXED_WORKSHOP_NAMES
from ..models import Craft, CraftType, Operation, RecordStatus, Workshop
from ..selectors import crafts_with_context, employees_with_context, operations_with_context, workshops_with_statistics
from ..services import create_config, update_config, update_employee_workshop
from .serializers import CraftSerializer, OperationSerializer, WorkshopEmployeeSerializer, WorkshopSerializer


def _parse_uuid(value, field_name):
    if not value:
        return None
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: f"{field_name} 参数不是有效的 UUID。"}) from exc


def _django_validation_details(exc):
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"detail": exc.messages}


class BaseConfigViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    model_class = None

    def actor_employee(self):
        return getattr(self.request, "employee", None)

    def _response_with_etag(self, instance, response_status=status.HTTP_200_OK):
        response = Response({"data": self.get_serializer(instance).data}, status=response_status)
        response["ETag"] = etag_for_instance(instance)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self._response_with_etag(self.get_object())

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            instance = create_config(
                model_class=self.model_class,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except DjangoValidationError as exc:
            raise ValidationError(_django_validation_details(exc)) from exc
        except IntegrityError as exc:
            raise ValidationError({"detail": "存在重复配置，请检查唯一字段后重试。"}) from exc
        return self._response_with_etag(self.get_queryset().get(pk=instance.pk), status.HTTP_201_CREATED)

    def _update(self, request, *, partial):
        current = self.get_object()
        serializer = self.get_serializer(current, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            instance = update_config(
                model_class=self.model_class,
                instance_id=current.pk,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except self.model_class.DoesNotExist as exc:
            raise NotFound("配置资料不存在。") from exc
        except DjangoValidationError as exc:
            raise ValidationError(_django_validation_details(exc)) from exc
        except IntegrityError as exc:
            raise ValidationError({"detail": "存在重复配置，请检查唯一字段后重试。"}) from exc
        return self._response_with_etag(self.get_queryset().get(pk=instance.pk))

    def update(self, request, *args, **kwargs):
        return self._update(request, partial=kwargs.pop("partial", False))

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True)


class WorkshopViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """固定车间只读接口，供员工和厂内工艺选择。"""

    serializer_class = WorkshopSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee]
    action_permission_map = {
        "list": None,
        "retrieve": None,
    }

    def get_queryset(self):
        queryset = Workshop.objects.all()
        status_value = self.request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in RecordStatus.values:
                raise ValidationError({"status": "状态参数不正确。"})
            queryset = queryset.filter(status=status_value)
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(name__icontains=keyword)
        fixed_order = Case(
            *[When(name=name, then=Value(index)) for index, name in enumerate(FIXED_WORKSHOP_NAMES)],
            output_field=IntegerField(),
        )
        return workshops_with_statistics(queryset).annotate(_fixed_order=fixed_order).order_by("_fixed_order", "id")


class WorkshopEmployeeViewSet(BaseConfigViewSet):
    serializer_class = WorkshopEmployeeSerializer
    model_class = Employee
    http_method_names = ["get", "patch", "put", "delete", "head", "options"]
    action_permission_map = {
        "list": "workshop_config.view_workshopemployee",
        "retrieve": "workshop_config.view_workshopemployee",
        "summary": "workshop_config.view_workshopemployee",
        "update": "workshop_config.change_workshopemployee",
        "partial_update": "workshop_config.change_workshopemployee",
        "destroy": "workshop_config.change_workshopemployee",
    }

    def get_queryset(self):
        queryset = active_department_employees("DEPT_PRODUCTION")
        workshop_id = _parse_uuid(self.request.query_params.get("workshop", "").strip(), "workshop")
        if workshop_id:
            queryset = queryset.filter(workshop_id=workshop_id)
        status_value = self.request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in {"ACTIVE", "LEFT"}:
                raise ValidationError({"status": "车间任职状态不正确。"})
            queryset = queryset.filter(workshop_status=status_value)
        supervisor_value = self.request.query_params.get("is_supervisor", "").strip().lower()
        if supervisor_value:
            if supervisor_value not in {"true", "false", "1", "0"}:
                raise ValidationError({"is_supervisor": "是否主管参数必须为 true 或 false。"})
            queryset = queryset.filter(workshop_is_supervisor=supervisor_value in {"true", "1"})
        position = self.request.query_params.get("position", "").strip()
        if position:
            queryset = queryset.filter(workshop_position__icontains=position)
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(Q(display_name__icontains=keyword) | Q(employee_code__icontains=keyword)
                                       | Q(workshop_position__icontains=keyword))
        return employees_with_context(queryset).order_by("workshop__name", "workshop_position", "display_name", "id")

    def _update(self, request, *, partial):
        current = self.get_object()
        serializer = self.get_serializer(current, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        instance = update_employee_workshop(instance_id=current.pk, validated_data=serializer.validated_data,
                                            actor_employee=self.actor_employee(), request=request)
        return self._response_with_etag(instance)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        counts = active_department_employees("DEPT_PRODUCTION").aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(workshop__isnull=False, workshop_status="ACTIVE")),
            left=Count("id", filter=Q(workshop_status="LEFT")),
            active_supervisors=Count("id", filter=Q(workshop__isnull=False, workshop_status="ACTIVE", workshop_is_supervisor=True)),
        )
        return Response({"data": counts})

    def destroy(self, request, *args, **kwargs):
        current = self.get_object()
        update_employee_workshop(instance_id=current.pk, actor_employee=self.actor_employee(), request=request,
                                 validated_data={"workshop": None, "workshop_position": "", "workshop_is_supervisor": False, "workshop_status": "ACTIVE"})
        return Response(status=status.HTTP_204_NO_CONTENT)


class CraftViewSet(BaseConfigViewSet):
    serializer_class = CraftSerializer
    model_class = Craft
    action_permission_map = {
        "list": "workshop_config.view_craft",
        "retrieve": "workshop_config.view_craft",
        "summary": "workshop_config.view_craft",
        "create": "workshop_config.add_craft",
        "update": "workshop_config.change_craft",
        "partial_update": "workshop_config.change_craft",
    }

    def get_queryset(self):
        queryset = Craft.objects.all()
        craft_type = self.request.query_params.get("craft_type", "").strip().upper()
        if craft_type:
            if craft_type not in CraftType.values:
                raise ValidationError({"craft_type": "工艺类型参数不正确。"})
            queryset = queryset.filter(craft_type=craft_type)
        workshop_id = _parse_uuid(self.request.query_params.get("workshop", "").strip(), "workshop")
        if workshop_id:
            queryset = queryset.filter(workshop_id=workshop_id)
        status_value = self.request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in RecordStatus.values:
                raise ValidationError({"status": "状态参数不正确。"})
            queryset = queryset.filter(status=status_value)
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(Q(name__icontains=keyword) | Q(workshop__name__icontains=keyword))
        return crafts_with_context(queryset).order_by("craft_type", "name", "id")

    @action(detail=False, methods=["get"])
    def summary(self, request):
        counts = Craft.objects.aggregate(
            total=Count("id"),
            internal=Count("id", filter=Q(craft_type=CraftType.INTERNAL)),
            external=Count("id", filter=Q(craft_type=CraftType.EXTERNAL)),
            active=Count("id", filter=Q(status=RecordStatus.ACTIVE)),
        )
        return Response({"data": counts})


class OperationViewSet(BaseConfigViewSet):
    serializer_class = OperationSerializer
    model_class = Operation
    action_permission_map = {
        "list": "workshop_config.view_operation",
        "retrieve": "workshop_config.view_operation",
        "summary": "workshop_config.view_operation",
        "create": "workshop_config.add_operation",
        "update": "workshop_config.change_operation",
        "partial_update": "workshop_config.change_operation",
    }

    def get_queryset(self):
        queryset = Operation.objects.all()
        craft_id = _parse_uuid(self.request.query_params.get("craft", "").strip(), "craft")
        if craft_id:
            queryset = queryset.filter(craft_id=craft_id)
        craft_type = self.request.query_params.get("craft_type", "").strip().upper()
        if craft_type:
            if craft_type not in CraftType.values:
                raise ValidationError({"craft_type": "工艺类型参数不正确。"})
            queryset = queryset.filter(craft__craft_type=craft_type)
        workshop_id = _parse_uuid(self.request.query_params.get("workshop", "").strip(), "workshop")
        if workshop_id:
            queryset = queryset.filter(craft__workshop_id=workshop_id)
        status_value = self.request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in RecordStatus.values:
                raise ValidationError({"status": "状态参数不正确。"})
            queryset = queryset.filter(status=status_value)
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(operation_number__icontains=keyword)
                | Q(product_name__icontains=keyword)
                | Q(name__icontains=keyword)
                | Q(craft__name__icontains=keyword)
            )
        return operations_with_context(queryset).order_by("operation_number", "id")

    @action(detail=False, methods=["get"])
    def summary(self, request):
        counts = Operation.objects.aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(status=RecordStatus.ACTIVE)),
            inactive=Count("id", filter=Q(status=RecordStatus.INACTIVE)),
        )
        return Response({"data": counts})
