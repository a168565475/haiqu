from drf_spectacular.utils import OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import mixins, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, RoleProfile
from .. import services
from .. import account_services, team_services
from ..models import SalesTeam
from ..catalog import catalog
from .base import AccessViewSet, IF_MATCH
from .organization_views import RoleDepartmentActions, EmployeeDepartmentActions
from .deletion_views import DeletionActions
from ..deletion_services import DELETED_REASON
from ..selectors import business_scope_enforcement, effective_access
from ..permissions import CanManageAccounts, CanReadAccessDirectory
from apps.core.api.permissions import HasActiveEmployee
from rest_framework.permissions import IsAuthenticated
from .serializers import (
    AccessEmployeeSerializer, CatalogEntrySerializer, EffectiveAccessSerializer,
    EmployeeRolesSerializer, GrantReplaceSerializer, RoleCreateSerializer,
    RoleSerializer, RoleUpdateSerializer,
    AccountCreateSerializer, AccountStatusSerializer, PasswordResetSerializer,
    TeamCreateSerializer, TeamUpdateSerializer, TeamMembersSerializer, TeamSerializer,
)

class CatalogViewSet(AccessViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, CanReadAccessDirectory]
    serializer_class = CatalogEntrySerializer

    @extend_schema(responses=CatalogEntrySerializer(many=True))
    def list(self, request):
        return Response(catalog())

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=['get'], url_path='scope-options')
    def scope_options(self, request):
        from ..resource_scopes import scope_options
        return Response(scope_options())


@extend_schema_view(
    create=extend_schema(request=RoleCreateSerializer, responses={201: RoleSerializer}),
    partial_update=extend_schema(request=RoleUpdateSerializer, responses=RoleSerializer, parameters=[IF_MATCH]),
)
class RoleViewSet(DeletionActions, RoleDepartmentActions, mixins.ListModelMixin, AccessViewSet):
    deletion_kind = "roles"
    def get_permissions(self):
        if self.action in {'list', 'retrieve', 'grants'}:
            return [IsAuthenticated(), HasActiveEmployee(), CanReadAccessDirectory()]
        return super().get_permissions()

    queryset = RoleProfile.objects.exclude(archive_reason=DELETED_REASON).select_related("auth_group").order_by("role_code")
    serializer_class = RoleSerializer

    def respond(self, role, status=200):
        return Response(RoleSerializer(role).data, status=status, headers={"ETag": etag_for_instance(role)})

    def retrieve(self, request, pk=None):
        return self.respond(self.get_object())

    def create(self, request):
        serializer = RoleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(services.create_role(request, serializer.validated_data), status=201)

    def partial_update(self, request, pk=None):
        serializer = RoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(services.update_role(request, pk, serializer.validated_data))

    @extend_schema(responses=RoleSerializer)
    @action(detail=True, methods=["get"])
    def grants(self, request, pk=None):
        return self.respond(self.get_object())

    @extend_schema(request=GrantReplaceSerializer, responses=RoleSerializer, parameters=[IF_MATCH])
    @grants.mapping.put
    def replace_grants(self, request, pk=None):
        serializer = GrantReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(services.replace_grants(request, pk, serializer.validated_data["grants"]))

    @extend_schema(request=RoleCreateSerializer, responses={201: RoleSerializer}, parameters=[IF_MATCH])
    @action(detail=True, methods=["post"])
    def copy(self, request, pk=None):
        serializer = RoleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(services.copy_role(request, pk, serializer.validated_data), status=201)


class AccessEmployeeViewSet(DeletionActions, EmployeeDepartmentActions, mixins.ListModelMixin, AccessViewSet):
    deletion_kind = "employees"
    def get_permissions(self):
        if self.action in {'list', 'roles', 'effective'}:
            return [IsAuthenticated(), HasActiveEmployee(), CanReadAccessDirectory()]
        if self.action in {'account', 'account_status', 'reset_password', 'delete_preview', 'delete_selected'}:
            return [IsAuthenticated(), HasActiveEmployee(), CanManageAccounts()]
        return super().get_permissions()

    queryset = Employee.objects.filter(archived_at__isnull=True).select_related("user", "wecom_binding").order_by("employee_code")
    serializer_class = AccessEmployeeSerializer

    def respond(self, employee):
        return Response(AccessEmployeeSerializer(employee).data, headers={"ETag": etag_for_instance(employee)})

    @extend_schema(request=AccountCreateSerializer, responses={201: AccessEmployeeSerializer}, parameters=[IF_MATCH])
    @action(detail=True, methods=["post"])
    def account(self, request, pk=None):
        serializer = AccountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        response = self.respond(account_services.create_account(request, pk, serializer.validated_data))
        response.status_code = 201
        return response

    @extend_schema(request=AccountStatusSerializer, responses=AccessEmployeeSerializer, parameters=[IF_MATCH])
    @account.mapping.patch
    def account_status(self, request, pk=None):
        serializer = AccountStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(account_services.set_account_status(request, pk, serializer.validated_data["is_active"]))

    @extend_schema(request=PasswordResetSerializer, responses=AccessEmployeeSerializer, parameters=[IF_MATCH])
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(account_services.reset_password(request, pk, serializer.validated_data["password"]))

    @action(detail=True, methods=["get"])
    def roles(self, request, pk=None):
        return self.respond(self.get_object())

    @extend_schema(request=EmployeeRolesSerializer, responses=AccessEmployeeSerializer, parameters=[IF_MATCH])
    @roles.mapping.put
    def replace_roles(self, request, pk=None):
        serializer = EmployeeRolesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(services.replace_employee_roles(request, pk, serializer.validated_data["role_ids"]))

    @extend_schema(responses=EffectiveAccessSerializer)
    @action(detail=True, methods=["get"], url_path="effective-access")
    def effective(self, request, pk=None):
        employee = self.get_object()
        if employee.user_id is None:
            return Response({"active": False, "is_superuser": False, "roles": [], "actions": {},
                             "legacy_sources": [], "version": "NO_ACCOUNT", "business_scope_enforcement": business_scope_enforcement()})
        return Response(effective_access(employee.user))


class AccessAuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ["id", "actor_employee_code_snapshot", "actor_name_snapshot", "object_type", "object_id",
                  "action", "before_data", "after_data", "occurred_at", "request_id"]


class AccessAuditViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, AccessViewSet):
    queryset = AuditLog.objects.filter(object_type__in=["ACCESS_ROLE", "ACCESS_EMPLOYEE", "ACCESS_TEAM", "ACCESS_ORGANIZATION"]).order_by("-occurred_at", "-id")
    serializer_class = AccessAuditSerializer


class SalesTeamViewSet(mixins.ListModelMixin, AccessViewSet):
    queryset = SalesTeam.objects.select_related("manager").order_by("code")
    serializer_class = TeamSerializer

    def respond(self, team, status=200):
        return Response(TeamSerializer(team).data, status=status, headers={"ETag": etag_for_instance(team)})

    def retrieve(self, request, pk=None):
        return self.respond(self.get_object())

    @extend_schema(request=TeamCreateSerializer, responses={201: TeamSerializer})
    def create(self, request):
        serializer = TeamCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(team_services.create_team(request, serializer.validated_data), 201)

    @extend_schema(request=TeamUpdateSerializer, responses=TeamSerializer, parameters=[IF_MATCH])
    def partial_update(self, request, pk=None):
        serializer = TeamUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(team_services.update_team(request, pk, serializer.validated_data))

    @extend_schema(request=TeamMembersSerializer, responses=TeamSerializer, parameters=[IF_MATCH])
    @action(detail=True, methods=["post"])
    def members(self, request, pk=None):
        serializer = TeamMembersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(team_services.add_members(request, pk, serializer.validated_data["employee_ids"]))
