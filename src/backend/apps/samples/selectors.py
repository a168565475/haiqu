from django.db.models import Q

from apps.customers.selectors import accessible_customers

from .models import SampleRequest, SampleShipment


def _legacy_accessible_sample_requests(request, permission_codename):
    if request.user.is_superuser or request.user.has_perm("samples.view_all_samplerequest"):
        return SampleRequest.objects.all()
    employee = getattr(request, "employee", None)
    own_request = Q(requested_by_employee=employee) if employee is not None else Q(pk__in=[])
    application_scope = Q(pk__in=[])
    if permission_codename in {"view_samplerequest", "review_sample_application"} and request.user.has_perm("samples.review_sample_application"):
        application_scope = ~Q(application_payload_hash="")
    material_stages = {
        'edit_sample_materials': ['MATERIALS_PENDING', 'WAREHOUSE_PENDING', 'PROCUREMENT_PENDING', 'MATERIALS_READY', 'MATERIAL_ISSUE_PENDING', 'METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING', 'FINISHED'],
        'review_sample_materials': ['WAREHOUSE_PENDING', 'PROCUREMENT_PENDING', 'MATERIALS_READY', 'MATERIAL_ISSUE_PENDING', 'MATERIAL_ISSUE_REVIEW', 'METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING', 'FINISHED'],
        'view_sample_procurement': ['PROCUREMENT_PENDING', 'METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING', 'FINISHED'],
    }
    for code, stages in material_stages.items():
        if permission_codename in {'view_samplerequest', code} and request.user.has_perm('samples.' + code):
            application_scope |= ~Q(application_payload_hash='') & Q(status__in=stages)
    if permission_codename == 'change_samplerequest' and request.user.has_perm('samples.edit_sample_materials'):
        application_scope |= ~Q(application_payload_hash='') & Q(status__in=['MATERIAL_ISSUE_PENDING', 'MATERIAL_ISSUE_REVIEW', 'METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING'])
    return SampleRequest.objects.filter(
        Q(customer_account__in=accessible_customers(request, permission_codename)) | own_request | application_scope
    ).distinct()


def accessible_sample_requests(request, permission_codename):
    from apps.access_control import module_policy, sales_policy
    if not module_policy.enabled():
        return _legacy_accessible_sample_requests(request, permission_codename)
    code = sales_policy.canonical_permission(permission_codename)
    if code is None or not module_policy.has_permission(request, code):
        return SampleRequest.objects.none()
    access = sales_policy.access_for(request)
    scopes = set(access['actions'].get(code, {}).get('scopes', []))
    if access['is_superuser'] or scopes & {'MODULE', 'ALL'}:
        return SampleRequest.objects.all()
    _, owners = sales_policy.allowed_owners(request, code)
    customers = sales_policy.current_primary_assignments().filter(employee__in=owners).values('customer_account_id')
    allowed = Q(customer_account_id__in=customers) | Q(customer_account__isnull=True, requested_by_employee__in=owners)
    legacy = {row['permission'] for row in access['legacy_sources']}
    for old in {code, module_policy.LEGACY_ALIASES.get(code)} & legacy:
        allowed |= Q(pk__in=_legacy_accessible_sample_requests(request, old.split('.', 1)[1]).values('pk'))
    return SampleRequest.objects.filter(allowed).distinct()


def sample_requests_with_context(queryset=None):
    if queryset is None:
        queryset = SampleRequest.objects.all()
    return queryset.select_related(
        "customer_account",
        "transaction_entity",
        "customer_contact",
        "owner_employee",
        "source_inquiry",
        "source_quotation_version__quotation",
        "requested_by_employee",
        "created_by_employee",
        "reference_image",
        "material_request__procurement_request",
    ).prefetch_related(
        "material_request__procurement_request__arrivals",
        "material_request__procurement_request__purchase_sources__purchase_order_line__purchase_order",
        "items",
        "products__category",
        "products__task_sheet_file__uploaded_by_employee",
        "products__details__product_color",
        "products__sampling_details__image_file__uploaded_by_employee",
        "collaborators",
        "fee_records__decided_by_employee",
        "fee_records__free_confirmed_by_employee",
        "approval_links__approval_request__current_approver_employee",
        "approval_links__approval_request__requested_by_employee",
        "shipments__items__sample_item",
        "shipments__shipped_by_employee",
        "shipments__events__recorded_by_employee",
        "feedback_records__customer_contact",
        "feedback_records__recorded_by_employee",
        "feedback_records__requotation_source_version__quotation",
        "feedback_records__resulting_quotation_version__quotation",
        "feedback_records__requotation_created_by_employee",
        "file_links__business_file__uploaded_by_employee",
        "workflow_records__business_file",
        "workflow_records__operated_by_employee",
        "sla_links__sla_tracking__sla_policy",
        "task_links__business_task",
    )


def shipments_with_context(queryset=None):
    if queryset is None:
        queryset = SampleShipment.objects.all()
    return queryset.select_related(
        "sample_request",
        "sample_request__customer_account",
        "shipped_by_employee",
        "fee_warning_acknowledged_by_employee",
    ).prefetch_related("items__sample_item", "events__recorded_by_employee")
