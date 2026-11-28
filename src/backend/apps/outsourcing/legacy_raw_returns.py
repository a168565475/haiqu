from collections import defaultdict

from django.db.models import F

from .models import OutsourcingRawReturnLine


def raw_returns_by_dispatch(dispatch_lines):
    returns = defaultdict(list)
    lines = OutsourcingRawReturnLine.objects.filter(
        dispatch_line_id__in=dispatch_lines.order_by().values("pk"),
        record__order_id=F("dispatch_line__dispatch__order_id"),
        record__factory_id=F("dispatch_line__material_item__allocation__factory_id"),
    ).values_list("dispatch_line_id", "quantity", "meter_quantity", "piece_quantity_equivalent")
    for dispatch_id, quantity, meters, pieces in lines.iterator():
        returns[dispatch_id].append((quantity, meters, pieces))
    return returns
