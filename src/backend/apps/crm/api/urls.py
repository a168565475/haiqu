from rest_framework.routers import SimpleRouter

from .views import CommunicationViewSet


router = SimpleRouter()
router.register("communications", CommunicationViewSet, basename="communication")

urlpatterns = router.urls
