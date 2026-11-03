from rest_framework.routers import SimpleRouter

from .views import ProductionTaskImportViewSet


router = SimpleRouter()
router.register('production-task-imports', ProductionTaskImportViewSet, basename='production-task-import')
urlpatterns = router.urls
