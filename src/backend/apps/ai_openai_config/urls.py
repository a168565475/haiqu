from rest_framework.routers import SimpleRouter

from .views import OpenAIKeyConfigViewSet


router = SimpleRouter()
router.register("ai-openai-configs", OpenAIKeyConfigViewSet, basename="ai-openai-config")
urlpatterns = router.urls

