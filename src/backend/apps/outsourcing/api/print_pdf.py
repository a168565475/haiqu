from django.http import FileResponse
from django.utils.cache import add_never_cache_headers
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes
from rest_framework import serializers


PRINT_KIND_PARAMETER = OpenApiParameter(
    'kind', str, enum=['processing', 'spray'], default='processing',
    description='文档版式。仅管材喷塑单支持 spray。',
)
PRINT_WAREHOUSE_PARAMETER = OpenApiParameter('warehouse_stage', str, enum=['all'])
PRINT_PDF_RESPONSES = {(200, 'application/pdf'): OpenApiTypes.BINARY}


def print_kind(request, *, spray_allowed=False):
    choices = ['processing', 'spray'] if spray_allowed else ['processing']
    return serializers.ChoiceField(choices).run_validation(request.query_params.get('kind', 'processing'))


def print_pdf_response(detail, *, kind, tube=False):
    from ..print_pdf import PDF_LABELS, build_outsourcing_pdf

    response = FileResponse(
        build_outsourcing_pdf(detail, kind=kind, tube=tube), as_attachment=True,
        filename=f"{detail['order_number']}_{PDF_LABELS[kind]}.pdf", content_type='application/pdf',
    )
    add_never_cache_headers(response)
    return response
