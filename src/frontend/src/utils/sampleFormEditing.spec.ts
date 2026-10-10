import { describe, expect, it } from 'vitest'
import type { SampleDetail, SampleProduct, SampleReportingProductEdit } from '@/types/sample'
import { buildSampleReportingPayload } from './sampleFormEditing'

function product(id: string): SampleProduct {
  return {
    id, line_number: 1, source_inquiry_item_id: `source-${id}`, source_quotation_line_id: null,
    category_id: 'category', category_name: '椅子', product_name: '折叠椅', specification: '',
    task_sheet_file_id: `task-${id}`, task_sheet_file_name: '任务.jpg', task_sheet_content_type: 'image/jpeg', task_sheet_size_bytes: 100,
    length_cm: '60.00', armrest_width_cm: null, seat_width_cm: '45.50', back_height_cm: null, seat_height_cm: null,
    total_sample_quantity: 8,
    details: ['a', 'b'].map(key => ({
      id: `${id}-${key}`, product_color_id: `color-${key}`, color_card: '', color_name: '白色', color_code: '',
      sample_quantity: 4, tolerance: 'NONE', tolerance_display: '无', notes: '原有备注',
      cutting_reported_quantity: 0, metalwork_reported_quantity: 1, cutting_completed: false, metalwork_completed: false,
    })),
    sampling_details: [{
      id: `sampling-${id}`, line_number: 1, template_key: 'pipe', detail_type: '管材', category_label: '圆管',
      is_selected: true, description: '保留描述', image_file_id: `image-${id}`,
      image_file_name: '材料.png', image_content_type: 'image/png', image_size_bytes: 100,
    }],
  }
}

function sample(): SampleDetail {
  // 只构造本适配器读取的契约字段；不作为运行时业务数据。
  return {
    id: 'request', status: 'PMC_REVIEW', manual_request_number: '123', customer_account: 'customer', customer_contact: 'contact',
    owner: { id: 'owner' }, shipping_method: 'MAIL', order_date: '2026-09-01', sample_due_date: '2026-09-18',
    delivery_batch: 'SINGLE', sample_type: 'PRE_SALE', is_repeat_order: false, submitted_on: '2026-09-01',
    purpose: '原说明', products: [product('one'), product('two')],
    edit_capabilities: { mode: 'REPORT_ONLY', can_report_edit: true, can_full_edit: false, can_complete: false, can_cancel: false },
  } as SampleDetail
}

function edits(value: SampleDetail): SampleReportingProductEdit[] {
  return value.products!.map(item => ({ id: item.id, details: item.details.map(detail => ({
    id: detail.id, cutting_reported_quantity: detail.cutting_reported_quantity,
    metalwork_reported_quantity: detail.metalwork_reported_quantity,
    cutting_completed: detail.cutting_completed, metalwork_completed: detail.metalwork_completed,
  })) }))
}

describe('仅报工编辑的无损适配', () => {
  it('按 UUID 合并报工修改，保留所有产品、来源、颜色、数量、图片关联行和零值', () => {
    const original = sample()
    const before = structuredClone(original)
    const changes = edits(original).reverse()
    changes[1]!.details.reverse()
    changes[1]!.details[1]!.cutting_reported_quantity = 4
    changes[1]!.details[1]!.cutting_completed = true
    const payload = buildSampleReportingPayload(original, changes, '新说明')
    expect(payload.products.map(item => item.id)).toEqual(['one', 'two'])
    expect(payload.products[0]).toMatchObject({ source_inquiry_item_id: 'source-one', specification: '', length_cm: '60.00', armrest_width_cm: null })
    expect(payload.products[0]!.details[0]).toMatchObject({
      id: 'one-a', product_color_id: 'color-a', color_code: '', sample_quantity: 4, tolerance: 'NONE', notes: '原有备注',
      cutting_reported_quantity: 4, cutting_completed: true, metalwork_reported_quantity: 1,
    })
    expect(payload.products[0]!.details[1]!.cutting_reported_quantity).toBe(0)
    expect(payload.products[0]!.sampling_details[0]).toMatchObject({ id: 'sampling-one', client_key: 'sampling-one', description: '保留描述' })
    expect(payload).toMatchObject({ customer_contact_id: 'contact', submitted_on: '2026-09-01', purpose: '新说明' })
    expect(original).toEqual(before)
  })

  it('不强制补齐只读的展示色卡、色号、规格或空打样信息行', () => {
    const original = sample()
    original.products![0]!.sampling_details = []
    expect(buildSampleReportingPayload(original, edits(original), '').products[0]!.sampling_details).toEqual([])
  })

  it.each([-1, 1.5, 5, NaN, Infinity])('拒绝非法报工数量 %s', value => {
    const original = sample()
    const changes = edits(original)
    changes[0]!.details[0]!.metalwork_reported_quantity = value
    expect(() => buildSampleReportingPayload(original, changes, '')).toThrow('报工数量')
  })

  it('允许清空报工输入为零，拒绝用默认数量掩盖源数量缺失', () => {
    const original = sample()
    const changes = edits(original)
    changes[0]!.details[0]!.metalwork_reported_quantity = null
    expect(buildSampleReportingPayload(original, changes, '').products[0]!.details[0]!.metalwork_reported_quantity).toBe(0)
    original.products![0]!.details[0]!.sample_quantity = null
    expect(() => buildSampleReportingPayload(original, changes, '')).toThrow('数量或颜色数据不完整')
  })

  it('拒绝删产品、重复产品或把别的产品报工行混入本申请', () => {
    const original = sample()
    const changes = edits(original)
    expect(() => buildSampleReportingPayload(original, changes.slice(1), '')).toThrow('产品信息不完整')
    expect(() => buildSampleReportingPayload(original, [changes[0]!, changes[0]!], '')).toThrow('产品信息不完整')
    changes[0]!.details[0]!.id = 'two-a'
    expect(() => buildSampleReportingPayload(original, changes, '')).toThrow('原申请')
  })

  it('拒绝重复报工行', () => {
    const original = sample()
    const changes = edits(original)
    changes[0]!.details[1] = changes[0]!.details[0]!
    expect(() => buildSampleReportingPayload(original, changes, '')).toThrow('报工行与原申请不一致')
  })

  it('不允许只读申请保存，不补造缺失提交日期', () => {
    const original = sample()
    original.edit_capabilities!.mode = 'READ_ONLY'
    expect(() => buildSampleReportingPayload(original, edits(original), '')).toThrow('不允许')
    original.edit_capabilities!.mode = 'REPORT_ONLY'
    original.submitted_on = null
    expect(() => buildSampleReportingPayload(original, edits(original), '')).toThrow('基础数据不完整')
  })

  it('限制特殊说明长度且不修改只读文字', () => {
    const original = sample()
    original.products![0]!.details[0]!.notes = '  原始备注  '
    expect(buildSampleReportingPayload(original, edits(original), '').products[0]!.details[0]!.notes).toBe('  原始备注  ')
    expect(() => buildSampleReportingPayload(original, edits(original), '字'.repeat(2001))).toThrow('2000')
  })
})
