"""同一外发单据中的管材与裁片分支。"""

CUTTING_SOURCES = {'PUBLIC_CUTTING', 'SEWING'}
DIRECT_SOURCES = {'METAL', 'SEWING'}
CUTTING_CRAFT_CODES = {'EMBROIDERY', 'SCREEN_PRINTING', 'CUTTING', 'SEWING'}
CUTTING_FIELDS = ('pieces_per_set', 'fabric_material', 'fabric_specification', 'fabric_color',
                  'completed_craft_name', 'unit')


def source_category(source_kind):
    return 'cutting' if source_kind in CUTTING_SOURCES else 'tube'


def output_unit(source_kind):
    return '套' if source_kind in CUTTING_SOURCES else '支'


def display_operations(source_kind, operations):
    if source_kind not in CUTTING_SOURCES:
        return operations
    return [{**row, 'raw_quantity': row['quantity'],
             'original_unit': '片' if row.get('counting_mode') == 'PIECE' else '套',
             'quantity': str(row['completed_sets'])} for row in operations]


def lock_source_product(product_line_id, source_kind):
    if source_kind in CUTTING_SOURCES:
        from apps.inventory.sewing_processing_services import lock_sewing_product_scope
        return lock_sewing_product_scope(product_line_id)
    from apps.inventory.tube_processing_services import lock_tube_product_scope
    return lock_tube_product_scope(product_line_id)
