from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


PDF_LABELS = {'processing': '委外加工单', 'spray': '管材喷塑计划'}
FONT_DIR = Path(__file__).resolve().parent.parent / 'procurement' / 'fonts'
pdfmetrics.registerFont(TTFont('OutsourcingText', str(FONT_DIR / 'NotoSansSC-Regular.ttf')))
pdfmetrics.registerFont(TTFont('OutsourcingTitle', str(FONT_DIR / 'NotoSerifSC-Bold.ttf')))
TEXT = ParagraphStyle('OutsourcingText', fontName='OutsourcingText', fontSize=9, leading=12, wordWrap='CJK')
CENTER = ParagraphStyle('OutsourcingCenter', parent=TEXT, alignment=TA_CENTER)
TITLE = ParagraphStyle('OutsourcingTitle', parent=CENTER, fontName='OutsourcingTitle', fontSize=18, leading=24)
CONTENT_WIDTH = A4[0] - 42 * mm
DETAIL_WIDTHS = [15.15] * 6 + [9.1]
SHANGHAI = ZoneInfo('Asia/Shanghai')


def _text(value):
    return (str(value).strip() if value is not None else '') or '—'


def _timestamp(value):
    if not value:
        return '—'
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    return stamp.astimezone(SHANGHAI).strftime('%Y-%m-%d %H:%M:%S')


def _paragraph(value, style=TEXT):
    return Paragraph(escape(_text(value)).replace('\n', '<br/>'), style)


def _table(rows, widths, *, repeat=0, commands=(), grid=True, centered=False):
    style = CENTER if centered else TEXT
    table = LongTable(
        [[_paragraph(value, style) if value != '' else '' for value in row] for row in rows],
        colWidths=[CONTENT_WIDTH * width / 100 for width in widths], repeatRows=repeat,
        hAlign='LEFT', splitInRow=1, minRowHeights=[6.5 * mm] * len(rows),
    )
    borders = [('GRID', (0, 0), (-1, -1), .75, colors.black)] if grid else []
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), mm), ('RIGHTPADDING', (0, 0), (-1, -1), mm),
        ('TOPPADDING', (0, 0), (-1, -1), .6 * mm), ('BOTTOMPADDING', (0, 0), (-1, -1), .6 * mm),
        *borders, *commands,
    ]))
    return table


def _detail_table(title, headings, rows):
    empty = [('SPAN', (0, 2), (-1, 2))] if not rows else []
    return _table(
        [[title, *([''] * 6)], headings, *(rows or [['暂无明细', *([''] * 6)]])],
        DETAIL_WIDTHS, repeat=2, commands=[('SPAN', (0, 0), (-1, 0)), *empty],
    )


def _tube_processing_rows(order):
    number = order['task_order_number']
    quantity = order['quantity']
    plans = [[
        '是' if order['status'] == 'COMPLETED' else '否', number, order['item_number'] or order['product_number'],
        order['product_name'], order['planned_quantity'], order['color'], order['specification'],
    ]]
    materials = []
    for line in order['lines']:
        specification = _text(line['specification'])
        if order['category'] != 'cutting' and line['cutting_length_mm'] not in (None, ''):
            specification += f" × {line['cutting_length_mm']}mm"
        materials.append([
            number, line['part_name'], line['pieces_per_product'], quantity, line['quantity'],
            line['unit'] if order['part_flow'] else order['output_unit'], specification,
            line['raw_color'], line['material'],
        ])
    materials.extend([
        number, row['name'], row['unit_consumption'], quantity, row['quantity'], row['unit'],
        row['specification'], row['color'], row['material'],
    ] for row in order['materials'])
    return plans, materials


def _regular_processing_rows(order):
    number = order['sales_order_number']
    complete = '是' if order['status'] == 'COMPLETED' else '否'
    plans, materials = [], []
    for row in order['products']:
        product = row['product']
        plans.append([
            complete, number, product.get('item_number') or product.get('product_number'), product.get('product_name'),
            row['planned_quantity'], product.get('color_name'), product.get('specification'),
        ])
        for item in row['processing_items']:
            for allocation in item['allocations']:
                materials.extend([
                    number, entry['name'], entry['unit_consumption'], row['order_quantity'],
                    entry['planned_issue_quantity'], entry['unit'], entry['specification'], entry['color'], entry['material'],
                ] for entry in allocation['materials'])
    return plans, materials


def _processing_story(order, *, tube):
    created = _timestamp(order['created_at'])
    order_number = order['order_number']
    if tube:
        task = order['task_number']
        author, craft, delivery = order['created_by_name'], order['craft_name'], order['expected_return_date']
        factories = dict.fromkeys(row['factory_name'] for row in [*order['lines'], *order['materials']] if row['factory_name'])
        plans, materials = _tube_processing_rows(order)
    else:
        task = order['production_task_number']
        author, craft, delivery = order['created_by']['name'], order['craft']['name'], order['delivery_date']
        factories = order['factory_names']
        plans, materials = _regular_processing_rows(order)
    story = [
        _paragraph(PDF_LABELS['processing'], TITLE), Spacer(1, 3.5 * mm),
        _table([
            [f'生产任务单号：{_text(task)}', f'提交人：{_text(author)}'],
            [f'提交时间：{created}', f"更新时间：{_timestamp(order['updated_at'])}"],
        ], [45.5, 54.5], grid=False),
        _table([
            ['委外加工单编号', '委外工艺'], [order_number, craft],
            ['委外加工厂', '制单人'], ['、'.join(factories) or '—', author],
            ['承包人', '制单日期'], ['', created[:10]], ['交货日期', ''], [delivery, ''],
        ], [45.5, 54.5], commands=[('SPAN', (0, 6), (1, 6)), ('SPAN', (0, 7), (1, 7))]),
        Spacer(1, 2 * mm),
        _detail_table('主计划明细', ['外发是否完成', '订单号', '货号', '产品名称', '排产数量', '颜色', '规格'], plans),
        Spacer(1, 2 * mm),
        _detail_table('材料明细', ['订单号', '品名', '单个用量', '订单量', '需外发数量', '单位', '规格'],
                      [row[:7] for row in materials]),
    ]
    if materials:
        story.append(_table([['颜色', '材质'], *[row[7:] for row in materials]], DETAIL_WIDTHS[:2], repeat=1))
    return story


def _spray_story(order):
    rows = [[
        row['factory_name'], row['part_name'], row['tube_diameter'] or row['specification'], row['cutting_length_mm'],
        row['pieces_per_product'], order['quantity'], row['quantity'], row['spray_color'],
    ] for row in order['lines']]
    commands = [('SPAN', (2, 0), (3, 0)), ('SPAN', (3, -1), (4, -1)), ('SPAN', (5, -1), (7, -1))]
    if not rows:
        rows = [['暂无明细', '', '', '', '', '', '', '']]
        commands.append(('SPAN', (0, 1), (-1, 1)))
    dispatch = order['actual_dispatch_date'] or order['planned_dispatch_date']
    return [
        _paragraph(f"{_text(order['task_order_number'])}单 嗨趣休闲用品有限公司喷塑计划", TITLE),
        Spacer(1, 9.5 * mm),
        _table([
            [f"产品名称：{_text(order['product_name'])}", f"回厂时间：{_text(order['expected_return_date'])}"],
            [f"来厂拉货时间：{_text(dispatch)}", f"外发单号：{_text(order['order_number'])}"],
            [f"生产任务单号：{_text(order['task_number'])}", ''],
        ], [41, 59], grid=False),
        Spacer(1, 2 * mm),
        _table([
            ['加工厂', '部件名称', '材料规格', '', '单耗量', '订单数量', '总支数', '喷塑颜色'],
            *rows,
            ['制表人：', order['created_by_name'], '日期：', _timestamp(order['created_at']), '',
             '喷塑回来请注明单号，否则一律拒收。仓库电话：15284640047张', '', ''],
        ], [13.3, 15.2, 12.4, 10.5, 10.8, 11.5, 12.8, 13.5], repeat=1, centered=True, commands=commands),
        Spacer(1, 13 * mm), _paragraph(f"备注：{order['remark']}"),
    ]


def build_outsourcing_pdf(order, *, kind, tube):
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, title=f"{order['order_number']} {PDF_LABELS[kind]}",
        leftMargin=21 * mm - 6, rightMargin=21 * mm - 6, topMargin=28 * mm - 6, bottomMargin=20 * mm - 6)
    document.build(_spray_story(order) if kind == 'spray' else _processing_story(order, tube=tube))
    output.seek(0)
    return output
