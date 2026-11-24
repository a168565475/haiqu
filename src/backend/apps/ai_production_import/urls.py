from rest_framework.routers import SimpleRouter

from .views import AiProductionImportViewSet


router = SimpleRouter()
router.register("ai-production-imports", AiProductionImportViewSet, basename="ai-production-import")
urlpatterns = router.urls
