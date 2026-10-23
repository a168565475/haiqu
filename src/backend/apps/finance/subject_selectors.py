from django.db.models import Case, CharField, Count, F, Q, Value, When
from django.db.models.functions import Concat

from .models import AccountingSubject


def subjects(filters=None):
    filters = filters or {}
    queryset = AccountingSubject.objects.select_related("parent__parent").annotate(
        full_path=Case(
            When(level=1, then=F("name")),
            When(level=2, then=Concat("parent__name", Value(" / "), "name")),
            default=Concat("parent__parent__name", Value(" / "), "parent__name", Value(" / "), "name"),
            output_field=CharField(),
        ),
        child_count=Count("children", distinct=True),
        grandchild_count=Count("children__children", distinct=True),
    ).order_by("full_path", "id")
    if filters.get("q"):
        queryset = queryset.filter(full_path__icontains=filters["q"])
    for field in ("level", "status", "parent_id"):
        if field in filters:
            queryset = queryset.filter(**{field: filters[field]})
    return queryset


def descendants(pk):
    return AccountingSubject.objects.filter(Q(parent_id=pk) | Q(parent__parent_id=pk))


def ancestors(subject):
    result = []
    current = subject.parent
    while current is not None:
        result.append(current)
        current = current.parent
    return list(reversed(result))
