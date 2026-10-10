from rest_framework.routers import SimpleRouter

from .views import SalesOrderViewSet


router = SimpleRouter()
router.register("sales-orders", SalesOrderViewSet, basename="sales-order")

urlpatterns = router.urls
