from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import FinanceAccountViewSet
from .subject_views import AccountingSubjectViewSet, SubjectTreeViewSet
from .statement_views import ReceivableStatementViewSet
from .source_views import FinanceSourceTaskViewSet
from .receipt_views import ReceiptAccountOptionsViewSet, ReceiptStatementViewSet, ReceiptUploadViewSet, ReceiptViewSet

router = SimpleRouter()
router.register("accounts", FinanceAccountViewSet, basename="finance-account")
router.register("subjects", AccountingSubjectViewSet, basename="finance-subject")
router.register("subject-tree", SubjectTreeViewSet, basename="finance-subject-tree")
router.register("statements", ReceivableStatementViewSet, basename="finance-statement")
router.register("source-tasks", FinanceSourceTaskViewSet, basename="finance-source-task")
router.register("receipts", ReceiptViewSet, basename="finance-receipt")
router.register("receipt-uploads", ReceiptUploadViewSet, basename="finance-receipt-upload")
router.register("account-options", ReceiptAccountOptionsViewSet, basename="finance-receipt-account-options")
urlpatterns = [
    path("statements/<uuid:pk>/receipts/", ReceiptStatementViewSet.as_view({"get": "receipts"}), name="finance-statement-receipts"),
    path("statements/<uuid:pk>/available-deposits/", ReceiptStatementViewSet.as_view({"get": "available_deposits"}), name="finance-statement-available-deposits"),
] + router.urls
