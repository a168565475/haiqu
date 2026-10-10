from apps.access_control import sales_policy
from django.db.models import Prefetch, Q
from django.utils import timezone

from apps.crm.models import CommunicationTaskLink
from apps.customers.models import CustomerTaskLink
from apps.customers.selectors import accessible_customers
from apps.inquiries.models import InquiryTaskLink
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit
from apps.quotations.models import QuotationVersionTaskLink
from apps.samples.models import SampleTaskLink

from .models import ApprovalRequest, BusinessTask, SlaTracking


OPEN_TASK_STATUSES = ["PENDING", "IN_PROGRESS"]


def team_employee_ids(employee):
    """严格按负责人当前主组织及有效下级组织计算团队成员。"""

    now = timezone.now()
    current_assignment = EmployeeOrganizationAssignment.objects.filter(
        employee=employee,
        is_primary=True,
        effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).select_related("organization_unit").first()
    if not current_assignment or current_assignment.organization_unit.archived_at is not None:
        return Employee.objects.none().values("id")

    unit_ids = {current_assignment.organization_unit_id}
    pending_parent_ids = list(unit_ids)
    while pending_parent_ids:
        child_ids = list(
            OrganizationUnit.objects.filter(
                parent_id__in=pending_parent_ids,
                status="ACTIVE",
                archived_at__isnull=True,
            ).values_list("id", flat=True)
        )
        pending_parent_ids = [unit_id for unit_id in child_ids if unit_id not in unit_ids]
        unit_ids.update(pending_parent_ids)

    return EmployeeOrganizationAssignment.objects.filter(
        organization_unit_id__in=unit_ids,
        is_primary=True,
        effective_from__lte=now,
        employee__status="ACTIVE",
        employee__archived_at__isnull=True,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).values("employee_id")


def filter_tasks_by_customer_access(queryset, request):
    """带来源客户的任务必须同时通过客户数据权限；无来源任务仍可见。"""

    if sales_policy.enabled():
        return filter_sales_task_sources(queryset, request)
    customers = accessible_customers(request, "view_customeraccount")
    if request.user.is_superuser or request.user.has_perm("customers.view_all_customer"):
        return queryset
    customer_ids = customers.values("id")
    customer_filter = (
        Q(customer_links__is_primary_source=True, customer_links__customer_account_id__in=customer_ids)
        | Q(
            communication_links__is_primary_source=True,
            communication_links__communication__customer_account_id__in=customer_ids,
        )
        | Q(inquiry_links__is_primary_source=True, inquiry_links__inquiry__customer_account_id__in=customer_ids)
        | Q(
            quotation_links__is_primary_source=True,
            quotation_links__quotation_version__quotation__customer_account_id__in=customer_ids,
        )
        | Q(sample_links__is_primary_source=True, sample_links__sample_request__customer_account_id__in=customer_ids)
    )
    no_primary_source = (
        Q(customer_links__isnull=True)
        & Q(communication_links__isnull=True)
        & Q(inquiry_links__isnull=True)
        & Q(quotation_links__isnull=True)
        & Q(sample_links__isnull=True)
    )
    return queryset.filter(customer_filter | no_primary_source).distinct()


def accessible_tasks(request, scope="ME", permission='workflow.view_businesstask'):
    from apps.access_control import module_policy
    if module_policy.enabled():
        return _scoped_tasks(request, scope, permission)
    queryset = BusinessTask.objects.all()
    employee = getattr(request, "employee", None)
    if not request.user.is_superuser and employee is None:
        return queryset.none()

    if scope == "ME":
        queryset = queryset.filter(assignee_employee=employee)
    elif scope == "CREATED_BY_ME":
        queryset = queryset.filter(created_by_employee=employee)
    elif scope == "LEGACY":
        queryset = queryset.filter(Q(assignee_employee=employee) | Q(created_by_employee=employee))
    elif scope == "TEAM":
        if not request.user.has_perm("workflow.view_team_businesstask") and not request.user.is_superuser:
            return queryset.none()
        queryset = queryset.filter(assignee_employee_id__in=team_employee_ids(employee))
    elif scope == "ALL":
        if not request.user.has_perm("workflow.view_all_businesstask") and not request.user.is_superuser:
            return queryset.none()
    elif scope == "ANY_ACCESS":
        if request.user.is_superuser or request.user.has_perm("workflow.view_all_businesstask"):
            pass
        elif request.user.has_perm("workflow.view_team_businesstask"):
            queryset = queryset.filter(
                Q(assignee_employee=employee)
                | Q(created_by_employee=employee)
                | Q(assignee_employee_id__in=team_employee_ids(employee))
            )
        else:
            queryset = queryset.filter(Q(assignee_employee=employee) | Q(created_by_employee=employee))
    else:
        return queryset.none()
    return filter_tasks_by_customer_access(queryset, request)


def _scoped_tasks(request, scope, permission):
    from apps.access_control import module_policy
    from apps.access_control.models import SalesTeamMembership
    access = sales_policy.access_for(request)
    if not access['active'] or not module_policy.has_permission(request, permission):
        return BusinessTask.objects.none()
    employee = request.employee
    teams = SalesTeamMembership.objects.filter(team__manager=employee, team__is_active=True).values('employee_id')
    own = Q(assignee_employee=employee) | Q(created_by_employee=employee)
    team = Q(assignee_employee_id__in=teams) | Q(created_by_employee_id__in=teams)
    scopes = set(access['actions'].get(permission, {}).get('scopes', []))
    allowed = Q(pk__in=[])
    if access['is_superuser'] or scopes & {'ALL', 'MODULE'}:
        allowed = Q()
    else:
        if 'OWN' in scopes:
            allowed |= own
        if 'TEAM' in scopes:
            allowed |= team
        legacy = {row['permission'] for row in access['legacy_sources']}
        if permission in legacy or module_policy.LEGACY_ALIASES.get(permission) in legacy:
            if 'workflow.view_all_businesstask' in legacy:
                allowed = Q()
            else:
                allowed |= own
                if 'workflow.view_team_businesstask' in legacy:
                    allowed |= Q(assignee_employee_id__in=team_employee_ids(employee))
    queryset = BusinessTask.objects.filter(allowed)
    legacy = {row['permission'] for row in access['legacy_sources']}
    team_filter = team
    if 'workflow.view_team_businesstask' in legacy:
        team_filter |= Q(assignee_employee_id__in=team_employee_ids(employee))
    filters = {'ME': Q(assignee_employee=employee), 'CREATED_BY_ME': Q(created_by_employee=employee),
        'LEGACY': own, 'TEAM': team_filter, 'ALL': Q(), 'ANY_ACCESS': Q()}
    if scope not in filters:
        return queryset.none()
    return filter_tasks_by_customer_access(queryset.filter(filters[scope]).distinct(), request)


def tasks_with_context(queryset=None):
    if queryset is None:
        queryset = BusinessTask.objects.all()
    return queryset.select_related(
        "assignee_employee",
        "created_by_employee",
        "contact",
    ).prefetch_related(
        Prefetch("customer_links", queryset=CustomerTaskLink.objects.filter(is_primary_source=True).select_related("customer_account"), to_attr="primary_customer_links"),
        Prefetch("communication_links", queryset=CommunicationTaskLink.objects.filter(is_primary_source=True).select_related("communication__customer_account"), to_attr="primary_communication_links"),
        Prefetch("inquiry_links", queryset=InquiryTaskLink.objects.filter(is_primary_source=True).select_related("inquiry__customer_account"), to_attr="primary_inquiry_links"),
        Prefetch("quotation_links", queryset=QuotationVersionTaskLink.objects.filter(is_primary_source=True).select_related("quotation_version__quotation__customer_account"), to_attr="primary_quotation_links"),
        Prefetch("sample_links", queryset=SampleTaskLink.objects.filter(is_primary_source=True).select_related("sample_request__customer_account"), to_attr="primary_sample_links"),
        "checklist_items",
        "reminders",
        "collaborators__employee",
    )


def accessible_approvals(request):
    queryset = ApprovalRequest.objects.all()
    from apps.access_control import module_policy
    if module_policy.enabled():
        # Fees are decided by the sample endpoint, which also updates its fee record.
        queryset = queryset.exclude(approval_type='SAMPLE_FEE_WAIVER')
    if sales_policy.enabled():
        from apps.quotations.models import QuotationVersion
        forbidden = QuotationVersion.objects.exclude(quotation__customer_account__in=accessible_customers(request, "view_quotationversion"))
        queryset = queryset.exclude(quotation_link__quotation_version__in=forbidden)
    if request.user.is_superuser:
        return queryset
    employee = getattr(request, "employee", None)
    if employee is None:
        return queryset.none()
    return queryset.filter(
        Q(current_approver_employee=employee) | Q(requested_by_employee=employee)
    ).distinct()


def approvals_with_context(queryset=None):
    if queryset is None:
        queryset = ApprovalRequest.objects.all()
    return queryset.select_related(
        "current_approver_employee",
        "requested_by_employee",
        "quotation_link__quotation_version",
        "quotation_link__quotation_version__quotation",
        "quotation_link__quotation_version__quotation__customer_account",
    )


def accessible_sla_trackings(request):
    from apps.customers.selectors import accessible_customers

    customers = accessible_customers(request, "view_slatracking")
    return SlaTracking.objects.filter(
        Q(inquiry_link__inquiry__customer_account__in=customers)
        | Q(quotation_link__quotation_version__quotation__customer_account__in=customers)
        | Q(sample_link__sample_request__customer_account__in=customers)
    ).distinct()


def sla_trackings_with_context(queryset=None):
    if queryset is None:
        queryset = SlaTracking.objects.all()
    return queryset.select_related(
        "sla_policy",
        "inquiry_link__inquiry",
        "quotation_link__quotation_version",
        "sample_link__sample_request",
    )


def filter_sales_task_sources(queryset, request):
    """Every attached sales source must be readable, including secondary links."""
    for link, model_label, customer_path, code in [
        ("customer_links__customer_account", "customers.CustomerAccount", "pk", "customers.view_customeraccount"),
        ("communication_links__communication", "crm.CustomerCommunication", "customer_account", "crm.view_customercommunication"),
        ("inquiry_links__inquiry", "inquiries.Inquiry", "customer_account", "inquiries.view_inquiry"),
        ("quotation_links__quotation_version", "quotations.QuotationVersion", "quotation__customer_account", "quotations.view_quotationversion"),
    ]:
        from django.apps import apps
        model = apps.get_model(model_label)
        forbidden = model.objects.exclude(**{f"{customer_path}__in": accessible_customers(request, code)})
        queryset = queryset.exclude(**{f"{link}__in": forbidden})
    from apps.access_control import module_policy
    if module_policy.enabled():
        from apps.samples.selectors import accessible_sample_requests
        from apps.samples.models import SampleRequest
        forbidden = SampleRequest.objects.exclude(pk__in=accessible_sample_requests(request, 'samples.view_samplerequest').values('pk'))
        queryset = queryset.exclude(sample_links__sample_request__in=forbidden)
    return queryset.distinct()
