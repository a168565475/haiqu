import django_filters
from django.db.models import Q, F, Sum, DecimalField, OuterRef, Subquery, Exists
from rest_framework.exceptions import ValidationError

from ..models import Inquiry, InquiryItem, InquiryPriority
from ..selectors import with_quotation_presence


class InquiryFilter(django_filters.FilterSet):
    customer_id = django_filters.UUIDFilter(field_name="customer_account_id")
    transaction_entity_id = django_filters.UUIDFilter(field_name="transaction_entity_id")
    customer_contact_id = django_filters.UUIDFilter(field_name="customer_contact_id")
    owner_employee_id = django_filters.UUIDFilter(method="filter_owner")
    country_code = django_filters.CharFilter(
        field_name="customer_account__primary_country_code",
        lookup_expr="iexact",
    )
    received_from = django_filters.IsoDateTimeFilter(field_name="received_at", lookup_expr="gte")
    received_to = django_filters.IsoDateTimeFilter(field_name="received_at", lookup_expr="lte")
    due_from = django_filters.IsoDateTimeFilter(field_name="requested_due_at", lookup_expr="gte")
    due_to = django_filters.IsoDateTimeFilter(field_name="requested_due_at", lookup_expr="lte")
    assignment_status = django_filters.CharFilter(method="filter_assignment_status")
    source_code = django_filters.CharFilter(field_name="inquiry_source", lookup_expr="iexact")
    product_q = django_filters.CharFilter(method="filter_product_q")
    sla_state = django_filters.CharFilter(method="filter_sla_state")
    amount_min = django_filters.NumberFilter(min_value=0, method="filter_amount_min")
    amount_currency = django_filters.CharFilter(method="filter_amount_currency")
    priority = django_filters.ChoiceFilter(choices=[*InquiryPriority.choices, ("UNSET", "未设置")], method="filter_priority")

    def filter_priority(self, queryset, name, value):
        return queryset.filter(priority="" if value == "UNSET" else value)

    def filter_owner(self, queryset, name, value):
        from apps.access_control import sales_policy
        if sales_policy.enabled():
            customers = sales_policy.current_primary_assignments().filter(employee_id=value).values("customer_account_id")
            return queryset.filter(customer_account_id__in=customers)
        return queryset.filter(owner_employee_id=value)

    def filter_queryset(self, queryset):
        amount = self.form.cleaned_data.get("amount_min")
        currency = self.form.cleaned_data.get("amount_currency") or ""
        if amount is not None or currency:
            if amount is None or len(currency) != 3 or not currency.isascii() or not currency.isalpha():
                raise ValidationError({"amount_min": "请同时填写非负金额和三位币种代码。"})
        return super().filter_queryset(queryset)

    def filter_amount_currency(self, queryset, name, value):
        return queryset

    def filter_amount_min(self, queryset, name, value):
        # 按目标价 × 数量、分币种求和；缺价询盘与列表的“待补齐”保持一致。
        currency = self.form.cleaned_data["amount_currency"].upper()
        items = InquiryItem.objects.filter(inquiry_id=OuterRef("pk"))
        totals = items.filter(target_currency_code=currency).order_by().values("inquiry_id").annotate(
            total=Sum(F("quantity") * F("target_unit_price"), output_field=DecimalField(max_digits=50, decimal_places=8))
        ).values("total")
        missing = items.filter(Q(target_unit_price__isnull=True) | Q(target_currency_code=""))
        return queryset.annotate(_target_total=Subquery(totals), _missing_target_price=Exists(missing)).filter(
            _missing_target_price=False, _target_total__gte=value,
        )
    has_quotation = django_filters.ChoiceFilter(choices=[("true", "已转报价"), ("false", "未转报价")], method="filter_has_quotation")

    def filter_has_quotation(self, queryset, name, value):
        return with_quotation_presence(queryset, self.request).filter(has_quotation=value == "true")

    def filter_assignment_status(self, queryset, name, value):
        from apps.access_control import sales_policy
        if sales_policy.enabled():
            customers = sales_policy.current_primary_assignments().values("customer_account_id")
            if value == "UNASSIGNED":
                return queryset.exclude(customer_account_id__in=customers)
            if value == "ASSIGNED":
                return queryset.filter(customer_account_id__in=customers)
            return queryset.none()
        if value == "UNASSIGNED":
            return queryset.filter(owner_employee__isnull=True)
        if value == "ASSIGNED":
            return queryset.filter(owner_employee__isnull=False)
        return queryset.none()

    def filter_product_q(self, queryset, name, value):
        return queryset.filter(
            Q(items__product_description__icontains=value)
            | Q(items__specification__icontains=value)
            | Q(items__color__icontains=value)
            | Q(items__material__icontains=value)
        ).distinct()

    def filter_sla_state(self, queryset, name, value):
        if value == "NONE":
            return queryset.exclude(sla_links__is_current=True)
        if value in {"DUE_SOON", "RISK", "BREACHED"}:
            from django.utils import timezone
            from ..worktime import due_soon_query, breached_query
            now = timezone.now()
            due = breached_query(now) if value == "BREACHED" else due_soon_query(now)
            if value == "RISK":
                due |= breached_query(now)
            return queryset.filter(due, sla_links__is_current=True).distinct()
        return queryset.none()

    class Meta:
        model = Inquiry
        fields = ["status", "customer_id", "transaction_entity_id", "customer_contact_id", "owner_employee_id", "country_code", "assignment_status", "source_code", "product_q", "sla_state"]
