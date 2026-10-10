from rest_framework.routers import SimpleRouter

from .views import EmailAccountViewSet


router = SimpleRouter()
router.register("email-accounts", EmailAccountViewSet, basename="email-account")

urlpatterns = router.urls

