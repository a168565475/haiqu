from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import Case, Count, IntegerField, Q, Value, When
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.organizations.models import Employee

from ..constants import FIXED_WORKSHOP_NAMES
from ..models import Craft, CraftType, Operation, RecordStatus, Workshop
from ..selectors import accessible_role_workshop_employees, accessible_workshop_employees, crafts_with_context, employee_workshop_ids, employees_with_context, operations_with_context, workshops_with_statistics
from ..services import create_config, update_config, update_employee_workshop
from .serializers import CraftSerializer, OperationSerializer, WorkshopEmployeeOptionsResponseSerializer, WorkshopEmployeeOptionsSerializer, WorkshopEmployeeSerializer, WorkshopSerializer


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


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter(
        "position_state", str, enum=["SET", "UNSET", "ROLE_PENDING", "ROLE_ALL"],
        description="SET/UNSET 按实际岗位筛选；ROLE_PENDING 按唯一有效角色对应车间筛选待设置人员；ROLE_ALL 合并授权已安排和角色待设置人员。",
    ),
]))
class WorkshopEmployeeViewSet(BaseConfigViewSet):
    serializer_class = WorkshopEmployeeSerializer
    model_class = Employee
    http_method_names = ["get", "patch", "put", "delete", "head", "options"]
    action_permission_map = {
        "list": "workshop_config.view_workshopemployee",
        "retrieve": "workshop_config.view_workshopemployee",
        "summary": "workshop_config.view_workshopemployee",
        "options_list": "workshop_config.view_workshopemployee",
        "update": "workshop_config.change_workshopemployee",
        "partial_update": "workshop_config.change_workshopemployee",
        "destroy": "workshop_config.change_workshopemployee",
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Employee.objects.none()
        permission = self.action_permission_map.get(self.action, "workshop_config.view_workshopemployee")
        queryset = accessible_workshop_employees(self.request, permission)
        if self.action in {"retrieve", "update", "partial_update", "destroy"}:
            role_queryset = accessible_role_workshop_employees(self.request, permission)
            queryset = Employee.objects.filter(
                Q(pk__in=queryset.values("pk")) | Q(pk__in=role_queryset.values("pk")),
            ).distinct()
        workshop_id = _parse_uuid(self.request.query_params.get("workshop", "").strip(), "workshop")
        status_value = self.request.query_params.get("status", "").strip().upper()
        supervisor_value = self.request.query_params.get("is_supervisor", "").strip().lower()
        position = self.request.query_params.get("position", "").strip()
        def apply_common_filters(rows):
            if status_value:
                if status_value not in {"ACTIVE", "LEFT"}:
                    raise ValidationError({"status": "车间任职状态不正确。"})
                rows = rows.filter(workshop_status=status_value)
            if supervisor_value:
                if supervisor_value not in {"true", "false", "1", "0"}:
                    raise ValidationError({"is_supervisor": "是否主管参数必须为 true 或 false。"})
                rows = rows.filter(workshop_is_supervisor=supervisor_value in {"true", "1"})
            if position:
                rows = rows.filter(workshop_position__icontains=position)
            return rows

        queryset = apply_common_filters(queryset)
        position_state = self.request.query_params.get("position_state", "").strip().upper()
        if position_state not in {"", "SET", "UNSET", "ROLE_PENDING", "ROLE_ALL"}:
            raise ValidationError({"position_state": "岗位状态参数不正确。"})
        if position_state in {"ROLE_PENDING", "ROLE_ALL"}:
            assigned_queryset = queryset.filter(workshop_id=workshop_id) if workshop_id and position_state == "ROLE_ALL" else queryset
            role_queryset = accessible_role_workshop_employees(
                self.request, permission, [workshop_id] if workshop_id else None,
            )
            role_queryset = apply_common_filters(role_queryset)
            if position_state == "ROLE_PENDING":
                queryset = role_queryset.filter(workshop_position="")
            else:
                queryset = Employee.objects.filter(
                    Q(pk__in=assigned_queryset.values("pk")) | Q(pk__in=role_queryset.values("pk")),
                ).distinct()
        elif workshop_id:
            queryset = queryset.filter(workshop_id=workshop_id)
        if position_state == "UNSET":
            queryset = queryset.filter(workshop__isnull=False, workshop_position="")
        elif position_state == "SET":
            queryset = queryset.exclude(workshop_position="")
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(Q(display_name__icontains=keyword) | Q(employee_code__icontains=keyword)
                                       | Q(workshop_position__icontains=keyword)
                                       | Q(role_assignments__role_profile__display_name__icontains=keyword)).distinct()
        return employees_with_context(queryset).order_by("workshop__name", "workshop_position", "display_name", "id")

    def _update(self, request, *, partial):
        current = self.get_object()
        serializer = self.get_serializer(current, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            instance = update_employee_workshop(instance_id=current.pk, validated_data=serializer.validated_data,
                                                actor_employee=self.actor_employee(), request=request)
        except Employee.DoesNotExist as exc:
            raise NotFound("员工资料不存在。") from exc
        except DjangoValidationError as exc:
            raise ValidationError(_django_validation_details(exc)) from exc
        return self._response_with_etag(employees_with_context(Employee.objects.filter(pk=instance.pk)).get())

    @extend_schema(responses=WorkshopEmployeeOptionsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="options", pagination_class=None)
    def options_list(self, request):
        def workshops(permission):
            queryset = Workshop.objects.order_by("name", "id")
            ids = employee_workshop_ids(request, permission)
            return queryset if ids is None else queryset.filter(pk__in=ids)

        data = WorkshopEmployeeOptionsSerializer({
            "workshops": workshops("workshop_config.view_workshopemployee"),
            "editable_workshops": workshops("workshop_config.change_workshopemployee"),
        }).data
        return Response({"data": data})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        counts = accessible_workshop_employees(request).aggregate(
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
