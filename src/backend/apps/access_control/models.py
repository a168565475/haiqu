from django.db import models

from apps.core.models import TimeStampedModel, uppercase_code_validator
from .catalog_extras import EXTRA_OPERATIONS


class AccessScope(models.TextChoices):
    OWN = "OWN", "本人"
    TEAM = "TEAM", "所管团队"
    ALL = "ALL", "全部"
    MODULE = "MODULE", "按模块"
    WORKSHOP = "WORKSHOP", "指定车间"
    CRAFT = "CRAFT", "指定外协工艺"
    STOCK = "STOCK", "库存来源"


class RoleActionGrant(TimeStampedModel):
    role = models.ForeignKey("organizations.RoleProfile", on_delete=models.PROTECT, related_name="action_grants")
    permission = models.ForeignKey("auth.Permission", on_delete=models.PROTECT, related_name="role_action_grants")
    scope = models.CharField(max_length=10, choices=AccessScope.choices)

    class Meta:
        db_table = "role_action_grant"
        default_permissions = ()
        permissions = [(code, label) for code, label, _module in EXTRA_OPERATIONS]
        constraints = [
            models.UniqueConstraint(fields=["role", "permission", "scope"], name="role_action_scope_unique"),
            models.CheckConstraint(condition=models.Q(scope__in=AccessScope.values), name="role_action_scope_valid"),
        ]


class RoleGrantResource(TimeStampedModel):
    # Explicit service deletion avoids querying this not-yet-deployed table on old installations.
    grant = models.ForeignKey(RoleActionGrant, on_delete=models.DO_NOTHING, related_name='resource_selections')
    workshop = models.ForeignKey('workshop_config.Workshop', null=True, blank=True, on_delete=models.PROTECT)
    craft = models.ForeignKey('workshop_config.Craft', null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = 'role_grant_resource'
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=(models.Q(workshop__isnull=False, craft__isnull=True)
                                              | models.Q(workshop__isnull=True, craft__isnull=False)),
                                   name='grant_resource_one_kind'),
            models.UniqueConstraint(fields=['grant', 'workshop'], name='grant_workshop_unique'),
            models.UniqueConstraint(fields=['grant', 'craft'], name='grant_craft_unique'),
        ]


class SalesTeam(TimeStampedModel):
    code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    name = models.CharField(max_length=150)
    manager = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="managed_sales_teams")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "access_sales_team"
        ordering = ["code"]
        default_permissions = ()


class SalesTeamMembership(TimeStampedModel):
    team = models.ForeignKey(SalesTeam, on_delete=models.PROTECT, related_name="memberships")
    employee = models.OneToOneField("organizations.Employee", on_delete=models.PROTECT, related_name="sales_team_membership")
    created_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="sales_memberships_created")

    class Meta:
        db_table = "access_sales_team_membership"
        default_permissions = ()
