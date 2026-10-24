"""产品属性分开保存；兼容旧页面使用的带标签规格文本。"""
import re

from apps.inquiries.models import format_inquiry_item_specification


def split_product_specification(specification):
    # 只识别系统明确生成的标签，不猜测“铝合金 黑色”等自由文本。
    remaining = specification or ''
    values = {}
    while remaining:
        match = re.search(r'(?:^|[；;])\s*(颜色|材质)\s*[:：]\s*([^；;]*?)\s*$', remaining)
        if not match or match[1] in values:
            break
        values[match[1]] = match[2]
        remaining = remaining[:match.start()]
    return {'specification': remaining.strip(),
            'color': values.get('颜色', ''), 'material': values.get('材质', '')}


def sample_product_attributes(product):
    values = split_product_specification(product.specification)
    colors = list(dict.fromkeys(detail.color_name_snapshot for detail in product.details.all()
                                if detail.color_name_snapshot))
    values['color'] = ' / '.join(colors) or values['color']
    values['material'] = product.material_snapshot or values['material']
    return values


def sample_product_specification_display(product):
    return format_inquiry_item_specification(**sample_product_attributes(product))


def sample_purchase_products(sample):
    """成品属性仅用于采购来源摘要，不替代原料明细的规格、颜色和材质。"""
    products = []
    for product in sample.products.all():
        values = sample_product_attributes(product)
        products.append({
            'product_line_id': str(product.pk), 'product_name': product.product_name,
            'specification': values['specification'], 'material': values['material'],
            'color_name': values['color'], 'color_card': '', 'color_code': '',
        })
    return products
