"""Authorization for reusing files and displaying cross-module activity."""
from django.apps import apps
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from . import sales_policy as policy


def readable_files(request):
    from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
    from apps.customers.selectors import accessible_customers
    from apps.sales_orders.selectors import accessible_sales_orders
    files = BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES)
    if not policy.enabled():
        return files
    if not policy.access_for(request)["active"]:
        return files.none()
    if policy.access_for(request)["is_superuser"]:
        return files
    # Upload ownership is sufficient only until the first business attachment.
    fresh = files.filter(uploaded_by_employee=getattr(request, "employee", None))
    for relation in BusinessFile._meta.related_objects:
        fresh = fresh.filter(**{f"{relation.name}__isnull": True})
    allowed = Q(pk__in=fresh.values("pk"))
    for path, code in [
        ("quotation_dispatch_evidence__quotation_version__quotation__customer_account", "quotations.view_quotationdispatchrecord"),
        ("complaint_attachments__complaint__customer_account", "customers.view_customercomplaint"),
        ("customer_links__customer_account", "customers.view_customeraccount"),
        ("communication_links__communication__customer_account", "crm.view_customercommunication"),
        ("inquiry_links__inquiry__customer_account", "inquiries.view_inquiryfilelink"),
        ("quotation_documents__quotation_version__quotation__customer_account", "quotations.view_quotationdocument"),
        ("quotation_links__quotation_version__quotation__customer_account", "quotations.view_quotationdocument"),
    ]:
        allowed |= Q(**{f"{path}__in": accessible_customers(request, code)})
    allowed |= Q(sales_order_evidence_links__sales_order__in=accessible_sales_orders(request))
    allowed |= Q(sales_order_collaboration_events__sales_order__in=accessible_sales_orders(request))
    if policy.has_permission(request, "samples.view_samplefilelink"):
        from apps.samples.selectors import accessible_sample_requests
        allowed |= Q(sample_links__sample_request__in=accessible_sample_requests(request, 'samples.view_samplefilelink'))
    return files.filter(allowed).distinct()


def require_file(request, business_file):
    from apps.files.models import USABLE_FILE_SCAN_STATUSES
    if business_file and business_file.scan_status not in USABLE_FILE_SCAN_STATUSES:
        raise PermissionDenied("文件尚未通过安全扫描，不能复用该文件。")
    if policy.enabled() and business_file and not readable_files(request).filter(pk=business_file.pk).exists():
        raise PermissionDenied("无权读取此文件的业务来源，不能复用该文件。")


def filter_activity(queryset, request, *, type_field="source_type", id_field="source_id"):
    if not policy.enabled():
        return queryset
    from apps.customers.selectors import accessible_customers
    from apps.sales_orders.selectors import accessible_sales_orders
    from apps.workflow.selectors import accessible_approvals, accessible_tasks
    if policy.access_for(request)["is_superuser"]:
        return queryset
    from .catalog import SALES_APPS
    models = {model._meta.model_name.upper(): model for model in apps.get_models() if model._meta.app_label in SALES_APPS}
    special = {
        "SALES_ORDER": accessible_sales_orders(request),
        "BUSINESS_TASK": accessible_tasks(request, scope="ANY_ACCESS"),
        "APPROVAL_REQUEST": accessible_approvals(request),
    }
    # Query only types present in this already customer-filtered activity stream.
    source_types = list(queryset.order_by().values_list(type_field, flat=True).distinct())
    for source in source_types:
        visible = special.get(source)
        if visible is None:
            model = models.get(source.replace("_", ""))
            if model is None:
                # Unknown sales event types fail closed; non-sales integration is stage 5.
                if source.startswith(("INQUIRY", "QUOTATION", "SALES_ORDER", "CUSTOMER_COMMUNICATION", "CUSTOMER_COMPLAINT")):
                    queryset = queryset.exclude(**{type_field: source})
                continue
            code = f"{model._meta.app_label}.view_{model._meta.model_name}"
            path = _customer_path(model)
            if path:
                visible = model.objects.filter(**{f"{path}__in": accessible_customers(request, code)})
            else:
                visible = model.objects.all() if policy.has_permission(request, code) else model.objects.none()
        queryset = queryset.exclude(Q(**{type_field: source}) & ~Q(**{f"{id_field}__in": visible.values("pk")}))
    return queryset


def _customer_path(model, depth=0):
    if model._meta.label_lower == "customers.customeraccount":
        return "pk"
    if depth >= 4:
        return None
    fields = {field.name: field for field in model._meta.fields}
    for name in ("customer_account", "customer_contact", "transaction_entity", "communication", "inquiry", "quotation", "quotation_version", "quotation_line", "complaint", "sales_order"):
        field = fields.get(name)
        if field is None or not field.is_relation:
            continue
        nested = _customer_path(field.related_model, depth + 1)
        if nested:
            return name if nested == "pk" else f"{name}__{nested}"
    return None
