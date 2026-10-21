from django.urls import path

from . import schedule_views, views


urlpatterns = [
    path("overview/", views.OverviewView.as_view(), name="attendance-overview"),
    path("records/monthly/", views.MonthlyRecordsView.as_view(), name="attendance-monthly"),
    path("records/daily/", views.DailyRecordsView.as_view(), name="attendance-daily"),
    path("records/raw/", views.RawRecordsView.as_view(), name="attendance-raw"),
    path("calendar/", views.CalendarView.as_view(), name="attendance-calendar"),
    path("vacation/", views.VacationView.as_view(), name="attendance-vacation"),
    path("schedule/", schedule_views.ScheduleView.as_view(), name="attendance-schedule"),
    path("rules/", schedule_views.RulesView.as_view(), name="attendance-rules"),
    path("sync-runs/", views.SyncStartView.as_view(), name="attendance-sync-start"),
    path("sync-runs/<uuid:run_id>/", views.SyncDetailView.as_view(), name="attendance-sync-detail"),
    path("sync-runs/<uuid:run_id>/step/", views.SyncStepView.as_view(), name="attendance-sync-step"),
]
