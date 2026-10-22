from rest_framework import serializers

from apps.core.api.concurrency import etag_for_instance
from apps.core.models import uppercase_code_validator
from apps.organizations.models import Employee, RoleProfile
from ..models import AccessScope, SalesTeam, SalesTeamMembership
from ..selectors import current_assignments, grant_rows


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({key: "不接受此字段。" for key in sorted(unknown)})
        return super().to_internal_value(data)


class RoleCreateSerializer(StrictSerializer):
    role_code = serializers.CharField(max_length=50, validators=[uppercase_code_validator])
    display_name = serializers.CharField(max_length=150)
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")


class RoleUpdateSerializer(StrictSerializer):
    display_name = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    archived = serializers.BooleanField(required=False)


class GrantSerializer(StrictSerializer):
    permission = serializers.CharField(max_length=180)
    scope = serializers.ChoiceField(choices=AccessScope.choices)
    resource_ids = serializers.ListField(child=serializers.UUIDField(), max_length=500, required=False, default=list)


class GrantReplaceSerializer(StrictSerializer):
    grants = GrantSerializer(many=True, max_length=2000)


class EmployeeRolesSerializer(StrictSerializer):
    role_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100)


class RoleSerializer(serializers.ModelSerializer):
    department_id = serializers.UUIDField(read_only=True, allow_null=True)
    archived = serializers.SerializerMethodField()
    grants = serializers.SerializerMethodField()
    etag = serializers.SerializerMethodField()
    assigned_employee_count = serializers.SerializerMethodField()

    class Meta:
        model = RoleProfile
        fields = ["id", "role_code", "display_name", "description", "department_id", "archived", "grants", "updated_at", "etag", "assigned_employee_count"]

    def get_assigned_employee_count(self, obj) -> int:
        from django.db.models import Q
        from django.utils import timezone
        from apps.organizations.models import EmployeeRoleAssignment
        now = timezone.now()
        return EmployeeRoleAssignment.objects.filter(role_profile=obj, effective_from__lte=now).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=now)).values("employee_id").distinct().count()

    def get_archived(self, obj) -> bool:
        return obj.archived_at is not None

    def get_grants(self, obj) -> list[dict[str, str]]:
        return grant_rows(obj)

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)


class AccessEmployeeSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", default=None, read_only=True)
    role_ids = serializers.SerializerMethodField()
    etag = serializers.SerializerMethodField()
    account_active = serializers.BooleanField(source="user.is_active", default=None, read_only=True)
    account_protected = serializers.SerializerMethodField()
    team_id = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    wecom_departments = serializers.JSONField(source="wecom_binding.department_snapshot", read_only=True, default=None, allow_null=True)

    class Meta:
        model = Employee
        fields = ["id", "employee_code", "display_name", "status", "username", "account_active", "account_protected", "team_id", "department", "wecom_departments", "role_ids", "etag"]

    def get_role_ids(self, obj) -> list[str]:
        return [str(pk) for pk in current_assignments(obj).values_list("role_profile_id", flat=True)]

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)

    def get_account_protected(self, obj) -> bool:
        return bool(obj.user_id and (obj.user.is_superuser or obj.user.is_staff or obj.user.username == "admin"))

    def get_team_id(self, obj) -> str | None:
        membership = SalesTeamMembership.objects.filter(employee=obj).first()
        return str(membership.team_id) if membership else None

    def get_department(self, obj) -> str:
        from django.db.models import Q
        from django.utils import timezone
        now = timezone.now()
        assignments = obj.organization_assignments.filter(effective_from__lte=now, organization_unit__archived_at__isnull=True, organization_unit__status="ACTIVE").filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
        return "、".join(assignments.values_list("organization_unit__unit_name", flat=True))


class AccountCreateSerializer(StrictSerializer):
    username = serializers.RegexField(r"^[\w.@+-]+$", max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)


class AccountStatusSerializer(StrictSerializer):
    is_active = serializers.BooleanField()


class PasswordResetSerializer(StrictSerializer):
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)


class TeamCreateSerializer(StrictSerializer):
    code = serializers.CharField(max_length=50, validators=[uppercase_code_validator])
    name = serializers.CharField(max_length=150)
    manager_id = serializers.UUIDField()


class TeamUpdateSerializer(StrictSerializer):
    name = serializers.CharField(max_length=150, required=False)
    is_active = serializers.BooleanField(required=False)


class TeamMembersSerializer(StrictSerializer):
    employee_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100, allow_empty=False)


class TeamSerializer(serializers.ModelSerializer):
    manager_name = serializers.CharField(source="manager.display_name", read_only=True)
    member_ids = serializers.SerializerMethodField()
    etag = serializers.SerializerMethodField()

    class Meta:
        model = SalesTeam
        fields = ["id", "code", "name", "manager_id", "manager_name", "is_active", "member_ids", "etag"]

    def get_member_ids(self, obj) -> list[str]:
        return [str(pk) for pk in obj.memberships.values_list("employee_id", flat=True)]

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)


class CatalogEntrySerializer(serializers.Serializer):
    code = serializers.CharField()
    module = serializers.CharField()
    module_name = serializers.CharField()
    label = serializers.CharField()
    resource = serializers.CharField()
    resource_name = serializers.CharField()
    action = serializers.CharField()
    action_name = serializers.CharField()
    scopes = serializers.ListField(child=serializers.CharField())
    available = serializers.BooleanField()
    integration_stage = serializers.IntegerField()
    implied_permissions = serializers.ListField(child=serializers.CharField())


class EffectiveAccessSerializer(serializers.Serializer):
    active = serializers.BooleanField()
    is_superuser = serializers.BooleanField()
    roles = serializers.ListField(child=serializers.DictField())
    actions = serializers.DictField()
    legacy_sources = serializers.ListField(child=serializers.DictField())
    version = serializers.CharField()
    business_scope_enforcement = serializers.CharField()
