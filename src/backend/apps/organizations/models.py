from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Q

from apps.core.models import (
    ArchivableModel,
    DateTimeRange,
    TimeStampedModel,
    uppercase_code_condition,
    uppercase_code_validator,
)


class OrganizationStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "启用"
    INACTIVE = "INACTIVE", "停用"


class EmployeeStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "在职"
    INACTIVE = "INACTIVE", "停用"
    LEFT = "LEFT", "离职"


class OrganizationUnit(ArchivableModel):
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    unit_code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    unit_name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20,
        choices=OrganizationStatus.choices,
        default=OrganizationStatus.ACTIVE,
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "organization_unit"
        permissions = [("manage_organization", "管理部门与组织归属")]
        ordering = ["sort_order", "unit_code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=OrganizationStatus.values), name="org_unit_status_valid"),
            models.CheckConstraint(
                condition=uppercase_code_condition("unit_code"),
                name="org_unit_code_uppercase",
            ),
            models.CheckConstraint(
                condition=~Q(id=F("parent_id")),
                name="org_unit_parent_not_self",
            ),
        ]
        indexes = [
            models.Index(
                fields=["parent", "sort_order", "id"],
                condition=Q(archived_at__isnull=True),
                name="org_unit_parent_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.unit_code} - {self.unit_name}"


class Employee(ArchivableModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employee_profile",
    )
    employee_code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    display_name = models.CharField(max_length=150)
    email = models.EmailField(max_length=254, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    status = models.CharField(
        max_length=20,
        choices=EmployeeStatus.choices,
        default=EmployeeStatus.ACTIVE,
    )
    hired_at = models.DateField(null=True, blank=True)
    left_at = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "employee"
        ordering = ["employee_code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=EmployeeStatus.values), name="employee_status_valid"),
            models.CheckConstraint(
                condition=uppercase_code_condition("employee_code"),
                name="employee_code_uppercase",
            ),
            models.CheckConstraint(
                condition=Q(left_at__isnull=True) | Q(hired_at__isnull=True) | Q(left_at__gte=F("hired_at")),
                name="employee_valid_employment_dates",
            ),
        ]

    def __str__(self):
        return f"{self.employee_code} - {self.display_name}"


class EmployeeOrganizationAssignment(TimeStampedModel):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="organization_assignments")
    organization_unit = models.ForeignKey(
        OrganizationUnit,
        on_delete=models.PROTECT,
        related_name="employee_assignments",
    )
    position_title = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    assigned_by_employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="organization_assignments_created",
    )

    class Meta:
        db_table = "employee_organization_assignment"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=F("effective_from")),
                name="emp_org_valid_effective_range",
            ),
            ExclusionConstraint(
                name="emp_org_no_overlap",
                expressions=[
                    ("employee", RangeOperators.EQUAL),
                    ("organization_unit", RangeOperators.EQUAL),
                    (DateTimeRange("effective_from", "effective_to", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
            ),
            ExclusionConstraint(
                name="emp_primary_org_no_overlap",
                expressions=[
                    ("employee", RangeOperators.EQUAL),
                    (DateTimeRange("effective_from", "effective_to", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
                condition=Q(is_primary=True),
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization_unit", "employee"],
                condition=Q(effective_to__isnull=True),
                name="emp_org_current_unit_idx",
            ),
            models.Index(fields=["employee", "-effective_from", "-id"], name="emp_org_history_idx"),
        ]


class RoleProfile(ArchivableModel):
    department = models.ForeignKey(
        OrganizationUnit, null=True, blank=True, on_delete=models.PROTECT, related_name="roles",
    )
    auth_group = models.OneToOneField(
        "auth.Group",
        on_delete=models.PROTECT,
        related_name="role_profile",
    )
    role_code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    display_name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "role_profile"
        ordering = ["role_code"]
        constraints = [
            models.CheckConstraint(
                condition=uppercase_code_condition("role_code"),
                name="role_profile_code_uppercase",
            ),
        ]

    def __str__(self):
        return f"{self.role_code} - {self.display_name}"


class EmployeeRoleAssignment(TimeStampedModel):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="role_assignments")
    role_profile = models.ForeignKey(RoleProfile, on_delete=models.PROTECT, related_name="employee_assignments")
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    assigned_by_employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="role_assignments_created",
    )

    class Meta:
        db_table = "employee_role_assignment"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=F("effective_from")),
                name="emp_role_valid_effective_range",
            ),
            ExclusionConstraint(
                name="emp_role_no_overlap",
                expressions=[
                    ("employee", RangeOperators.EQUAL),
                    ("role_profile", RangeOperators.EQUAL),
                    (DateTimeRange("effective_from", "effective_to", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
            ),
        ]
        indexes = [
            models.Index(
                fields=["employee", "role_profile"],
                condition=Q(effective_to__isnull=True),
                name="emp_role_current_emp_idx",
            ),
            models.Index(
                fields=["role_profile", "employee"],
                condition=Q(effective_to__isnull=True),
                name="emp_role_current_role_idx",
            ),
        ]
