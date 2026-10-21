from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import HasActiveEmployee
from apps.core.models import uppercase_code_validator
from apps.organizations.models import Employee, OrganizationUnit
from .. import organization_services as services
from ..permissions import CanManageOrganization, CanReadAccessDirectory
from .serializers import RoleSerializer, StrictSerializer
from .base import AccessViewSet, IF_MATCH


class DepartmentCreateSerializer(StrictSerializer):
    unit_code = serializers.CharField(max_length=50, validators=[uppercase_code_validator])
    unit_name = serializers.CharField(max_length=200)
    parent_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    sort_order = serializers.IntegerField(min_value=0, max_value=2147483647, required=False, default=0)


class DepartmentUpdateSerializer(StrictSerializer):
    unit_name = serializers.CharField(max_length=200, required=False)
    sort_order = serializers.IntegerField(min_value=0, max_value=2147483647, required=False)
    status = serializers.ChoiceField(choices=["ACTIVE", "INACTIVE"], required=False)


class DepartmentSerializer(serializers.ModelSerializer):
    parent_id = serializers.UUIDField(read_only=True, allow_null=True)
    etag = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationUnit
        fields = ["id", "unit_code", "unit_name", "parent_id", "status", "sort_order", "etag"]

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)


class RoleDepartmentSerializer(StrictSerializer):
    department_id = serializers.UUIDField(allow_null=True)


class EmployeeDepartmentRowSerializer(StrictSerializer):
    department_id = serializers.UUIDField()
    is_primary = serializers.BooleanField()
    position_title = serializers.CharField(max_length=150, allow_blank=True, required=False, default="")


class EmployeeDepartmentsSerializer(StrictSerializer):
    departments = EmployeeDepartmentRowSerializer(many=True, max_length=100)


class EmployeeDepartmentHistorySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    department_id = serializers.UUIDField()
    department_name = serializers.CharField()
    is_primary = serializers.BooleanField()
    position_title = serializers.CharField()
    effective_from = serializers.DateTimeField()
    effective_to = serializers.DateTimeField(allow_null=True)


class EmployeeDepartmentsResponseSerializer(serializers.Serializer):
    employee_id = serializers.UUIDField()
    etag = serializers.CharField()
    departments = EmployeeDepartmentHistorySerializer(many=True)


ORGANIZATION_PERMISSIONS = [IsAuthenticated, HasActiveEmployee, CanManageOrganization]


class DepartmentViewSet(mixins.ListModelMixin, AccessViewSet):
    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            return [IsAuthenticated(), HasActiveEmployee(), CanReadAccessDirectory()]
        return super().get_permissions()

    permission_classes = ORGANIZATION_PERMISSIONS
    lookup_value_regex = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    queryset = OrganizationUnit.objects.filter(archived_at__isnull=True).order_by("sort_order", "unit_code")
    serializer_class = DepartmentSerializer

    def retrieve(self, request, pk=None):
        return self.respond(self.get_object())

    def respond(self, unit, status=200):
        return Response(DepartmentSerializer(unit).data, status=status, headers={"ETag": etag_for_instance(unit)})

    @extend_schema(request=DepartmentCreateSerializer, responses={201: DepartmentSerializer})
    def create(self, request):
        serializer = DepartmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(services.create_department(request, serializer.validated_data), 201)

    @extend_schema(request=DepartmentUpdateSerializer, responses=DepartmentSerializer, parameters=[IF_MATCH])
    def partial_update(self, request, pk=None):
        serializer = DepartmentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(services.update_department(request, pk, serializer.validated_data))


class RoleDepartmentActions:
    @extend_schema(request=RoleDepartmentSerializer, responses=RoleSerializer, parameters=[IF_MATCH])
    @action(detail=True, methods=["put"], permission_classes=ORGANIZATION_PERMISSIONS)
    def department(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        serializer = RoleDepartmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = services.set_role_department(request, pk, serializer.validated_data["department_id"])
        return Response(RoleSerializer(role).data, headers={"ETag": etag_for_instance(role)})


class EmployeeDepartmentActions:
    @extend_schema(responses=EmployeeDepartmentsResponseSerializer)
    @action(detail=True, methods=["get"], permission_classes=ORGANIZATION_PERMISSIONS)
    def departments(self, request, pk=None):
        from rest_framework.generics import get_object_or_404
        pk = serializers.UUIDField().run_validation(pk)
        employee = get_object_or_404(Employee, pk=pk, archived_at__isnull=True)
        return employee_departments_response(employee)

    @extend_schema(request=EmployeeDepartmentsSerializer, responses=EmployeeDepartmentsResponseSerializer, parameters=[IF_MATCH])
    @departments.mapping.put
    def replace_departments(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        serializer = EmployeeDepartmentsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return employee_departments_response(services.replace_employee_departments(request, pk, serializer.validated_data["departments"]))


def employee_departments_response(employee):
    return Response({"employee_id": str(employee.pk), "etag": etag_for_instance(employee),
                     "departments": services.assignment_snapshot(employee)}, headers={"ETag": etag_for_instance(employee)})
