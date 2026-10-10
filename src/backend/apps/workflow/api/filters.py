from datetime import timedelta

import django_filters
from django.db.models import Q
from django.utils import timezone

from apps.customers.models import CustomerTaskLink
from apps.crm.models import CommunicationTaskLink
from apps.inquiries.models import InquiryTaskLink
from apps.quotations.models import QuotationVersionTaskLink
from apps.samples.models import SampleTaskLink

from ..models import BusinessTask


class TaskFilter(django_filters.FilterSet):
    assignee_employee_id = django_filters.UUIDFilter(field_name="assignee_employee_id")
    task_type = django_filters.CharFilter(field_name="task_type")
    source_type = django_filters.CharFilter(method="filter_source_type")
    customer_id = django_filters.UUIDFilter(method="filter_customer")
    display_status = django_filters.CharFilter(method="filter_display_status")
    due_window = django_filters.CharFilter(method="filter_due_window")
    due_from = django_filters.IsoDateTimeFilter(field_name="due_at", lookup_expr="gte")
    due_to = django_filters.IsoDateTimeFilter(field_name="due_at", lookup_expr="lte")
    overdue = django_filters.BooleanFilter(method="filter_overdue")

    class Meta:
        model = BusinessTask
        fields = ["status", "priority", "task_type", "assignee_employee_id", "overdue"]

    def filter_overdue(self, queryset, name, value):
        if value:
            return queryset.filter(
                status__in=["PENDING", "IN_PROGRESS"],
                due_at__lt=timezone.now(),
            )
        return queryset

    def filter_due_window(self, queryset, name, value):
        now = timezone.now()
        local_now = timezone.localtime(now)
        today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        if value == "TODAY":
            return queryset.filter(due_at__gte=today_start, due_at__lt=tomorrow_start)
        if value == "OVERDUE":
            return self.filter_overdue(queryset, name, True)
        if value == "NEXT_7_DAYS":
            return queryset.filter(due_at__gte=tomorrow_start, due_at__lt=tomorrow_start + timedelta(days=7))
        if value == "NO_DUE_DATE":
            return queryset.filter(due_at__isnull=True)
        return queryset

    def filter_display_status(self, queryset, name, value):
        if value == "BLOCKED":
            return queryset.filter(work_state="BLOCKED")
        if value == "WAITING_CUSTOMER":
            return queryset.filter(work_state="WAITING_CUSTOMER")
        if value == "OVERDUE":
            return self.filter_overdue(queryset.exclude(work_state="BLOCKED"), name, True)
        return queryset.filter(status=value)

    def filter_source_type(self, queryset, name, value):
        mapping = {
            "CUSTOMER": "customer_links",
            "COMMUNICATION": "communication_links",
            "INQUIRY": "inquiry_links",
            "QUOTATION_VERSION": "quotation_links",
            "SAMPLE_REQUEST": "sample_links",
        }
        relation = mapping.get(value)
        if not relation:
            return queryset.none()
        return queryset.filter(**{f"{relation}__is_primary_source": True}).distinct()

    def filter_customer(self, queryset, name, value):
        # 先合并来源任务 ID，保留外层已有权限及状态过滤，避免五组 LEFT JOIN。
        task_ids = CustomerTaskLink.objects.filter(
            customer_account_id=value, is_primary_source=True,
        ).order_by().values("business_task_id").union(
            CommunicationTaskLink.objects.filter(
                communication__customer_account_id=value, is_primary_source=True,
            ).order_by().values("business_task_id"),
            InquiryTaskLink.objects.filter(
                inquiry__customer_account_id=value, is_primary_source=True,
            ).order_by().values("business_task_id"),
            QuotationVersionTaskLink.objects.filter(
                quotation_version__quotation__customer_account_id=value, is_primary_source=True,
            ).order_by().values("business_task_id"),
            SampleTaskLink.objects.filter(
                sample_request__customer_account_id=value, is_primary_source=True,
            ).order_by().values("business_task_id"),
        )
        return queryset.filter(pk__in=task_ids)
