from datetime import datetime, timedelta, timezone as datetime_timezone

from django.db.models import Count, Exists, OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.crm.models import CommunicationContactParticipant
from apps.workflow.models import TaskStatus

from .models import CustomerContact, CustomerContactMethod, CustomerContactRole


def customer_contact_summary(customer):
    """客户范围的统计不受列表筛选、分页影响，不读取全部联系方式及任务。"""
    now = timezone.now()
    active_roles = CustomerContactRole.objects.filter(effective_from__lte=now).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gt=now)
    ).order_by("role_type", "id")
    latest = CommunicationContactParticipant.objects.filter(
        customer_contact_id=OuterRef("pk"), communication__archived_at__isnull=True,
    ).order_by("-communication__occurred_at", "-communication_id")
    contacts = CustomerContact.objects.filter(customer_account=customer, archived_at__isnull=True).annotate(
        last_interaction_at=Subquery(latest.values("communication__occurred_at")[:1]),
        has_decision_role=Exists(active_roles.filter(customer_contact_id=OuterRef("pk"), role_type="DECISION_MAKER")),
    )
    summary = contacts.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(status="ACTIVE")),
        decision_maker=Count("pk", filter=Q(status="ACTIVE", has_decision_role=True)),
        primary=Count("pk", filter=Q(status="ACTIVE", is_primary_contact=True)),
        left=Count("pk", filter=Q(status="LEFT")),
        stale=Count("pk", filter=Q(status="ACTIVE") & (
            Q(last_interaction_at__isnull=True) | Q(last_interaction_at__lt=now - timedelta(days=30))
        )),
    )
    candidates = contacts.filter(status="ACTIVE").filter(Q(is_key_contact=True) | Q(has_decision_role=True)).annotate(
        priority_time=Coalesce("last_interaction_at", Value(datetime(1970, 1, 1, tzinfo=datetime_timezone.utc))),
    )
    latest_time = candidates.order_by("-priority_time").values_list("priority_time", flat=True).first()
    summary["priority_candidates"] = []
    if latest_time is not None:
        # 仅返回最近互动时间并列者，姓名继续由前端按中文排序，避免数据库排序规则改变推荐人。
        for contact in candidates.filter(priority_time=latest_time).only("id", "display_name", "position_title").prefetch_related(
            Prefetch("roles", queryset=active_roles, to_attr="summary_roles")
        ):
            summary["priority_candidates"].append({
                "id": str(contact.pk), "display_name": contact.display_name, "position_title": contact.position_title,
                "active_roles": [{"id": str(role.pk), "role_type": role.role_type, "role_type_display": role.get_role_type_display()} for role in contact.summary_roles],
                "last_interaction": {"occurred_at": contact.last_interaction_at} if contact.last_interaction_at else None,
            })
    return summary


def contacts_with_list_context(queryset):
    now = timezone.now()
    latest_participation = CommunicationContactParticipant.objects.filter(
        customer_contact_id=OuterRef("pk"),
        communication__archived_at__isnull=True,
    ).order_by("-communication__occurred_at", "-communication_id")
    return queryset.select_related(
        "customer_account", "transaction_entity", "source_contact"
    ).prefetch_related(
        Prefetch(
            "methods",
            queryset=CustomerContactMethod.objects.filter(archived_at__isnull=True).order_by(
                "-is_primary", "-is_preferred", "method_type", "id"
            ),
            to_attr="active_methods",
        ),
        Prefetch(
            "roles",
            queryset=CustomerContactRole.objects.filter(effective_from__lte=now).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=now)
            ).order_by("role_type", "id"),
            to_attr="active_roles_prefetched",
        ),
    ).annotate(
        last_interaction_at=Subquery(latest_participation.values("communication__occurred_at")[:1]),
        last_interaction_type=Subquery(latest_participation.values("communication__communication_type")[:1]),
        open_task_count=Count(
            "task_links",
            filter=Q(
                task_links__business_task__status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
                task_links__business_task__archived_at__isnull=True,
            ),
            distinct=True,
        ),
    )


def filter_contacts(queryset, params):
    q = params.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(display_name__icontains=q)
            | Q(english_name__icontains=q)
            | Q(position_title__icontains=q)
            | Q(department_name__icontains=q)
            | Q(customer_account__account_name__icontains=q)
            | Q(customer_account__account_code__icontains=q)
            | Q(methods__raw_value__icontains=q, methods__archived_at__isnull=True)
            | Q(methods__normalized_value__icontains=q, methods__archived_at__isnull=True)
        )
    if params.get("customer_id"):
        queryset = queryset.filter(customer_account_id=params["customer_id"])
    if params.get("status"):
        queryset = queryset.filter(status=params["status"])
    if params.get("role_type"):
        now = timezone.now()
        queryset = queryset.filter(roles__role_type=params["role_type"], roles__effective_from__lte=now).filter(
            Q(roles__effective_to__isnull=True) | Q(roles__effective_to__gt=now)
        )
    if params.get("method_type"):
        queryset = queryset.filter(
            methods__method_type=params["method_type"], methods__archived_at__isnull=True
        )
    if params.get("is_key_contact", "").lower() in {"true", "false"}:
        queryset = queryset.filter(is_key_contact=params["is_key_contact"].lower() == "true")

    archived = params.get("archived", "false").lower()
    if archived == "true":
        queryset = queryset.filter(archived_at__isnull=False)
    elif archived != "all":
        queryset = queryset.filter(archived_at__isnull=True)

    last_interaction = params.get("last_interaction")
    day_map = {"WITHIN_7_DAYS": 7, "WITHIN_30_DAYS": 30, "WITHIN_90_DAYS": 90}
    if last_interaction in day_map:
        queryset = queryset.filter(last_interaction_at__gte=timezone.now() - timedelta(days=day_map[last_interaction]))
    elif last_interaction == "NEVER":
        queryset = queryset.filter(last_interaction_at__isnull=True)

    ordering = params.get("ordering", "display_name")
    allowed_ordering = {
        "display_name", "-display_name", "customer_account__account_name",
        "-customer_account__account_name", "last_interaction_at", "-last_interaction_at",
        "updated_at", "-updated_at",
    }
    if ordering not in allowed_ordering:
        ordering = "display_name"
    return queryset.order_by(ordering, "id").distinct()
