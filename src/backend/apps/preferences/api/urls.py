from rest_framework.routers import SimpleRouter

from .views import SavedViewViewSet


router = SimpleRouter()
router.register("saved-views", SavedViewViewSet, basename="saved-view")

urlpatterns = router.urls
