from django.urls import path
from rest_framework.routers import DefaultRouter

from .image_views import BomLineImageDraftViewSet, BomLineImageViewSet
from .views import BomViewSet


router = DefaultRouter()
router.register("boms", BomViewSet, basename="bom")

image_collection = BomLineImageViewSet.as_view({"get": "list", "post": "create"})
image_detail = BomLineImageViewSet.as_view({"delete": "destroy"})
image_content = BomLineImageViewSet.as_view({"get": "content"})
draft_image_collection = BomLineImageDraftViewSet.as_view({"post": "create"})
draft_image_detail = BomLineImageDraftViewSet.as_view({"delete": "destroy"})
draft_image_content = BomLineImageDraftViewSet.as_view({"get": "content"})

urlpatterns = [
    path(
        "boms/<uuid:bom_id>/draft-line-images/",
        draft_image_collection,
        name="bom-line-image-draft-list",
    ),
    path(
        "boms/<uuid:bom_id>/draft-line-images/<uuid:draft_id>/",
        draft_image_detail,
        name="bom-line-image-draft-detail",
    ),
    path(
        "boms/<uuid:bom_id>/draft-line-images/<uuid:draft_id>/content/",
        draft_image_content,
        name="bom-line-image-draft-content",
    ),
    path(
        "boms/<uuid:bom_id>/lines/<uuid:line_id>/images/",
        image_collection,
        name="bom-line-image-list",
    ),
    path(
        "boms/<uuid:bom_id>/lines/<uuid:line_id>/images/<uuid:image_id>/",
        image_detail,
        name="bom-line-image-detail",
    ),
    path(
        "boms/<uuid:bom_id>/lines/<uuid:line_id>/images/<uuid:image_id>/content/",
        image_content,
        name="bom-line-image-content",
    ),
    *router.urls,
]
