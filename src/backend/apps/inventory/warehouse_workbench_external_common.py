from decimal import Decimal


def number(value):
    return format(Decimal(value).normalize(), 'f')


def quantity(name, unit, required, done, *, factory=''):
    return {'name': f'{name} · {factory}' if factory else name, 'unit': unit,
            'required': number(required), 'done': number(done), 'remaining': number(max(required - done, 0))}


def document(order, kind, key, task, product, factories, day, partial, lines):
    status = ('分批发出' if partial else '待发出') if key == 'dispatch' else ('部分回货' if partial else '待回货')
    row = {'id': str(order.pk), 'kind': kind, 'task_number': task, 'product': product,
           'number': order.order_number, 'party': '、'.join(sorted(set(filter(None, factories)))),
           'date': day.isoformat() if day else None, 'status': status}
    return row, lines


def event(record, kind, order_number, task_number, day, voucher, party, description):
    return {'id': str(record.pk), 'kind': kind, 'task_number': task_number, 'number': voucher,
            'date': day.isoformat(), 'party': party, 'description': f'{order_number} · {description}'}
