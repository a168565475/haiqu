from django.urls import path
from rest_framework.routers import DefaultRouter

from .image_views import BomLineImageDraftViewSet, BomLineImageViewSet
from .nesting_views import BomNestingJobViewSet
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
    path("boms/<uuid:bom_id>/nesting-jobs/", BomNestingJobViewSet.as_view({"get": "list", "post": "create"}), name="bom-nesting-list"),
    path("boms/<uuid:bom_id>/nesting-jobs/<uuid:job_id>/", BomNestingJobViewSet.as_view({"get": "retrieve"}), name="bom-nesting-detail"),
    path("boms/<uuid:bom_id>/nesting-jobs/<uuid:job_id>/calculate/", BomNestingJobViewSet.as_view({"post": "calculate"}), name="bom-nesting-calculate"),
    path("boms/<uuid:bom_id>/nesting-jobs/<uuid:job_id>/cancel/", BomNestingJobViewSet.as_view({"post": "cancel"}), name="bom-nesting-cancel"),
    path("boms/<uuid:bom_id>/nesting-jobs/<uuid:job_id>/source/", BomNestingJobViewSet.as_view({"get": "source"}), name="bom-nesting-source"),
    path("boms/<uuid:bom_id>/nesting-jobs/<uuid:job_id>/preview/", BomNestingJobViewSet.as_view({"get": "preview"}), name="bom-nesting-preview"),
    path("boms/<uuid:bom_id>/nesting-jobs/<uuid:job_id>/dxf/", BomNestingJobViewSet.as_view({"get": "dxf"}), name="bom-nesting-dxf"),
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
