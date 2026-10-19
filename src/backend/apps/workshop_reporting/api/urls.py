from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    ReportingContextView,
    PlanWageStatusView,
    ScheduleProgressStatusView,
    WageSchemeViewSet,
    WorkReportDayDetailView,
    WorkReportDayListView,
    WorkReportTaskListView,
    WorkReportTaskProductImageView,
    WorkReportViewSet,
)


router = SimpleRouter()
router.register("wage-schemes", WageSchemeViewSet, basename="wage-scheme")
router.register("work-reports", WorkReportViewSet, basename="work-report")

urlpatterns = [
    path("context/", ReportingContextView.as_view(), name="workshop-reporting-context"),
    path("plan-wage-statuses/", PlanWageStatusView.as_view(), name="workshop-reporting-plan-wage-statuses"),
    path("schedule-progress-statuses/", ScheduleProgressStatusView.as_view(), name="workshop-reporting-schedule-progress-statuses"),
    path("work-report-days/", WorkReportDayListView.as_view(), name="work-report-day-list"),
    path("work-report-tasks/", WorkReportTaskListView.as_view(), name="work-report-task-list"),
    path("work-report-tasks/<str:task_id>/products/<str:product_line_id>/image/", WorkReportTaskProductImageView.as_view(), name="work-report-task-product-image"),
    path("work-report-days/<str:production_date>/", WorkReportDayDetailView.as_view(), name="work-report-day-detail"),
] + router.urls
