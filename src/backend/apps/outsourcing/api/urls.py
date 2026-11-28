from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import OutsourcingFactoryViewSet, OutsourcingOrderViewSet
from .unified_views import UnifiedOutsourcingOrderViewSet
from .tube_views import TubeOutsourcingOrderViewSet
from .cut_piece_printing import urlpatterns as cut_piece_printing_urls
from .movements import OutsourcingMovementsView
from .powder_coating import PowderCoatingRemindersView, PowderCoatingView
from .sewing_tracking import SewingTrackingView
from .sewing_workbench import SewingWorkbenchViewSet


router = SimpleRouter()
router.register("outsourcing-factories", OutsourcingFactoryViewSet, basename="outsourcing-factory")
router.register("outsourcing-orders", OutsourcingOrderViewSet, basename="outsourcing-order")
router.register("unified-outsourcing-orders", UnifiedOutsourcingOrderViewSet, basename="unified-outsourcing-order")
router.register("tube-outsourcing-orders", TubeOutsourcingOrderViewSet, basename="tube-outsourcing-order")
router.register("sewing-outsourcing-workbench", SewingWorkbenchViewSet, basename="sewing-outsourcing-workbench")

urlpatterns = [path("sewing-tracking/", SewingTrackingView.as_view(), name="sewing-tracking-list"),
               path("outsourcing-movements/", OutsourcingMovementsView.as_view(), name="outsourcing-movements"),
               path("powder-coating-movements/", PowderCoatingView.as_view(), name="powder-coating-movements"),
               path("powder-coating-reminders/", PowderCoatingRemindersView.as_view(), name="powder-coating-reminders"),
               *router.urls, *cut_piece_printing_urls]

