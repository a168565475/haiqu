from .models import CustomerCommunication


def communications_with_details(queryset=None):
    if queryset is None:
        queryset = CustomerCommunication.objects.all()
    return queryset.select_related(
        "customer_account",
        "created_by_employee",
    ).prefetch_related(
        "employee_participants__employee",
        "contact_participants__customer_contact",
        "inquiry_links",
        "quotation_links",
        "sample_links",
        "file_links__business_file",
    )
