from rest_framework.routers import SimpleRouter

from .views import ApprovalViewSet, SlaTrackingViewSet, TaskViewSet


router = SimpleRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("approvals", ApprovalViewSet, basename="approval")
router.register("sla-trackings", SlaTrackingViewSet, basename="sla-tracking")

urlpatterns = router.urls
