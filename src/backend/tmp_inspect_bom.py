from apps.boms.models import Bom, BomLine
from apps.reference_data.models import FabricWidth, ProductColor
print('BOM', Bom.objects.count())
for title in ['面料类','辅料类','裁剪明细']:
    qs=BomLine.objects.filter(section__title=title).select_related('section__bom').order_by('id')[:8]
    print('\n', title)
    for x in qs:
        print(x.id, x.section.bom.bom_number, x.part_name, 'cat=',x.category,'unit=',x.unit,'unitc=',x.unit_consumption,'total=',x.total_consumption,'purchase=',x.purchase_consumption,'cut=',x.cut_piece_quantity,'raw=',x.raw_values)
print('widths', list(FabricWidth.objects.filter(status='ACTIVE', archived_at__isnull=True).values('id','width_value')))
print('colors', list(ProductColor.objects.filter(status='ACTIVE', archived_at__isnull=True).values('id','color_card','color_code','color_name')[:10]))
