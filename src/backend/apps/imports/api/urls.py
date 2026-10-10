from rest_framework.routers import SimpleRouter

from .views import ContactImportViewSet


router = SimpleRouter()
router.register("contact-imports", ContactImportViewSet, basename="contact-import")

urlpatterns = router.urls
