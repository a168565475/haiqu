import type { ProductionDeliveryBatchInput, ProductionTaskDetailInput, ProductionTaskInput, ProductionTaskOptions, ProductionTaskProductInput } from '@/types/productionTask'

export type AiTaskDetailDraft = Omit<ProductionTaskDetailInput, 'is_selected'> & { is_selected: boolean | null; source_note?: string }
export type AiTaskProductDraft = Omit<ProductionTaskProductInput, 'details' | 'currency_id' | 'unit_price' | 'exchange_rate'> & {
  currency_id: string
  unit_price: string
  exchange_rate: string
  details: AiTaskDetailDraft[]
  source_currency: string
  source_item_number: string
  source_color_card: string
}
export type AiDeliveryBatchDraft = ProductionDeliveryBatchInput & {
  batch_key: string
  product_key: string
  color: string
  packaging_method: string
  carton_quantity: string
}
export type AiTaskDraft = Omit<ProductionTaskInput, 'includes_tax' | 'is_repeat_order' | 'preproduction_sample_required' | 'delivery_method' | 'products' | 'delivery_batches'> & {
  includes_tax: boolean | null
  is_repeat_order: boolean | null
  preproduction_sample_required: boolean | null
  delivery_method: 'SINGLE' | 'SPLIT' | ''
  products: AiTaskProductDraft[]
  delivery_batches: AiDeliveryBatchDraft[]
}

export type AiTaskCreatePayload = Omit<ProductionTaskInput, 'includes_tax' | 'currency_id' | 'freight_amount' | 'other_fee_amount' | 'products'> & {
  includes_tax: boolean | null
  currency_id: string | null
  freight_amount: string | null
  other_fee_amount: string | null
  products: Array<Omit<ProductionTaskProductInput, 'currency_id' | 'unit_price' | 'exchange_rate' | 'details'> & {
    currency_id: string | null; unit_price: string | null; exchange_rate: string | null; details: AiTaskDetailDraft[]
  }>
}

export function sourceObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

// 冲突和缺失只保留原文用于核对，不能混入正式字段。
export function extracted(value: unknown): unknown {
  const field = sourceObject(value)
  if ('value' in field) return ['MISSING', 'CONFLICT', 'UNREADABLE'].includes(String(field.status)) ? null : field.value
  return value
}

export function extractedText(value: unknown): string {
  const result = extracted(value)
  return typeof result === 'string' || typeof result === 'number' ? String(result).trim() : ''
}

function extractedBoolean(value: unknown): boolean | null {
  const result = extracted(value)
  if (typeof result === 'boolean') return result
  if (['是', '含税', '需要', 'true'].includes(String(result))) return true
  if (['否', '不含税', '不需要', 'false'].includes(String(result))) return false
  return null
}

function sourceProducts(result: Record<string, unknown>) {
  return Array.isArray(result.products) ? result.products.map(sourceObject) : []
}

function currencyCode(value: unknown): string {
  const raw = extractedText(value).toUpperCase()
  return ['RMB', '人民币', '￥', '¥'].includes(raw) ? 'CNY' : raw
}

function sourceDetails(product: Record<string, unknown>, key: string): AiTaskDetailDraft[] {
  return Array.isArray(product.details) ? product.details.map((value, index) => {
    const row = sourceObject(value)
    const selection = sourceObject(row.is_selected)
    const description = sourceObject(row.description)
    const notes = [selection.note, description.note].filter(item => typeof item === 'string' && item)
    return { client_key: `${key}-d${index + 1}`.slice(0, 64), template_key: extractedText(row.template_key), detail_type: '', category_label: '',
      is_selected: extractedBoolean(row.is_selected), description: extractedText(row.description), source_note: [...new Set(notes)].join('；') }
  }) : []
}

function sourceBatches(task: Record<string, unknown>): AiDeliveryBatchDraft[] {
  return Array.isArray(task.delivery_batches) ? task.delivery_batches.map((value, index) => {
    const row = sourceObject(value)
    return { batch_key: extractedText(row.batch_key) || `batch-${index + 1}`, product_key: extractedText(row.product_key),
      color: extractedText(row.color), packaging_method: extractedText(row.packaging_method), carton_quantity: extractedText(row.carton_quantity),
      quantity: extractedText(row.quantity), delivery_date: extractedText(row.delivery_date), note: extractedText(row.notes ?? row.note) }
  }) : []
}

export function taskDraftFromResult(result: Record<string, unknown>): AiTaskDraft {
  const task = sourceObject(result.task)
  const repeat = extractedBoolean(task.is_repeat_order)
  const delivery = extractedText(task.delivery_method)
  return {
    task_number: extractedText(task.task_number), contract_number: '', contract_number_token: '',
    order_number: extractedText(task.task_number), order_source: repeat === true ? 'REPEAT' : 'NEW',
    order_date: extractedText(task.order_date), delivery_date: extractedText(task.delivery_date),
    salesperson_id: '', follower_ids: [], currency_id: '', includes_tax: extractedBoolean(task.includes_tax),
    tax_rate: [3, 5, 7].includes(Number(extractedText(task.tax_rate))) ? Number(extractedText(task.tax_rate)) as 3 | 5 | 7 : null,
    order_tolerance_percent: extractedText(task.order_tolerance_percent), is_repeat_order: repeat,
    preproduction_sample_required: extractedBoolean(task.preproduction_sample_required),
    delivery_method: delivery === 'SINGLE' || delivery === '一次交货' ? 'SINGLE' : delivery === 'SPLIT' || delivery === '分批交货' ? 'SPLIT' : '',
    special_requirements_html: extractedText(task.special_requirements_html ?? task.special_requirements),
    freight_amount: extractedText(task.freight_amount), other_fee_amount: extractedText(task.other_fee_amount),
    planned_start_date: extractedText(task.planned_start_date) || null, planned_end_date: extractedText(task.planned_end_date) || null,
    production_priority: ['URGENT', 'HIGH', 'NORMAL', 'LOW'].includes(extractedText(task.production_priority))
      ? extractedText(task.production_priority) as ProductionTaskInput['production_priority'] : undefined,
    production_batch_number: extractedText(task.production_batch_number), delivery_batches: sourceBatches(task),
    products: sourceProducts(result).map((product, index) => {
      const key = extractedText(product.product_key) || `product-${index + 1}`
      const currency = currencyCode(product.currency)
      return { client_key: key, product_id: null,
      product_color_id: null, color_code: extractedText(product.color_code), customer_product_name: extractedText(product.name),
      customer_specification: extractedText(product.specification), customer_color: extractedText(product.color),
      material: extractedText(product.material), quantity: extractedText(product.quantity), unit_id: null,
      currency_id: '', unit_price: extractedText(product.unit_price ?? product.unit_price_cny), exchange_rate: currency === 'CNY' ? '1.00000000' : '',
      source_currency: currency, source_item_number: extractedText(product.item_number), source_color_card: extractedText(product.color_card),
      special_requirements: extractedText(product.special_requirements), packaging_method: extractedText(product.packaging_method ?? product.packaging_requirements),
      retained_image_ids: [], details: sourceDetails(product, key),
    }}),
  }
}

export function restoreTaskDraft(result: Record<string, unknown>, saved: Record<string, unknown>): AiTaskDraft {
  const base = taskDraftFromResult(result)
  const snapshot = JSON.parse(JSON.stringify(saved)) as Record<string, unknown>
  const restored = { ...base, ...snapshot } as AiTaskDraft
  restored.products = Array.isArray(snapshot.products) ? snapshot.products.map((value, index) => ({
    ...base.products.find(row => row.client_key === sourceObject(value).client_key) || base.products[index],
    source_currency: '', source_item_number: '', source_color_card: '', ...sourceObject(value), details: Array.isArray(sourceObject(value).details) ? sourceObject(value).details : [],
  })) as AiTaskDraft['products'] : base.products
  restored.delivery_batches = Array.isArray(snapshot.delivery_batches) ? snapshot.delivery_batches.map((value, index) => ({
    batch_key: `batch-${index + 1}`, product_key: '', color: '', packaging_method: '', carton_quantity: '', ...sourceObject(value),
  })) as AiDeliveryBatchDraft[] : base.delivery_batches
  return restored
}

function unique<T>(values: T[]): T | undefined { return values.length === 1 ? values[0] : undefined }

export function detailTemplates(options: ProductionTaskOptions, key: string): AiTaskDetailDraft[] {
  return options.detail_template.map((item, index) => ({ client_key: `${key}-d${index + 1}`.slice(0, 64), template_key: item.key,
    detail_type: item.type, category_label: item.category, is_selected: null, description: '' }))
}

export function applyTaskOptions(draft: AiTaskDraft, result: Record<string, unknown>, options: ProductionTaskOptions): void {
  const task = sourceObject(result.task)
  const salesperson = extractedText(task.salesperson_name ?? task.salesperson)
  draft.salesperson_id = unique(options.salespeople.filter(row => row.display_name === salesperson || row.employee_code === salesperson))?.id || ''
  const follower = extractedText(task.follower_names ?? task.followers ?? task.follower_name)
  const names = follower.split(/[、,，;；]/).map(value => value.trim()).filter(Boolean)
  const matches = names.map(name => unique(options.employees.filter(row => row.display_name === name || row.employee_code === name)))
  draft.follower_ids = names.length && matches.every(Boolean) ? [...new Set(matches.map(row => row!.id))] : []
  sourceProducts(result).forEach((source, index) => {
    const row = draft.products[index]
    if (!row) return
    row.currency_id = unique(options.currencies.filter(item => item.code === currencyCode(source.currency)))?.id || ''
    if (options.currencies.find(item => item.id === row.currency_id)?.code === 'CNY') row.exchange_rate = '1.00000000'
    const unit = extractedText(source.unit)
    row.unit_id = unique(options.units.filter(item => item.unit_name === unit || item.unit_code === unit))?.id || null
    const code = extractedText(source.product_code ?? source.code)
    const itemNumber = extractedText(source.item_number)
    const product = unique(options.products.filter(item => code ? item.product_code === code : itemNumber ? item.item_number === itemNumber
      : Boolean(row.customer_product_name && row.customer_specification) && item.product_name === row.customer_product_name && item.specification === row.customer_specification))
    // 名称相同但规格不同时，不以主档覆盖原表值。
    if (product && (!row.customer_specification || product.specification === row.customer_specification)
      && (!row.unit_id || product.default_unit_id === row.unit_id)) row.product_id = product.id
    const color = unique(options.colors.filter(item => Boolean(row.source_color_card || row.color_code || row.customer_color)
      && (!row.source_color_card || item.color_card === row.source_color_card) && (!row.color_code || item.color_code === row.color_code)
      && (!row.customer_color || item.color_name === row.customer_color)))
    row.product_color_id = color?.id || null
    const recognized = row.details
    const knownKeys = new Set(options.detail_template.map(item => item.key))
    row.details = detailTemplates(options, row.client_key).map(template => {
      const detail = unique(recognized.filter(item => item.template_key === template.template_key))
      return detail ? { ...template, ...detail, client_key: template.client_key, detail_type: template.detail_type, category_label: template.category_label } : template
    })
    row.details.push(...recognized.filter(detail => !knownKeys.has(detail.template_key)).map((detail, index) => ({
      ...detail, client_key: `${row.client_key}-u${index + 1}`.slice(0, 64), source_note: detail.source_note || '未对应生产明细类别，请选择或填写。',
    })))
  })
  const currencies = [...new Set(draft.products.map(row => row.currency_id))]
  draft.currency_id = currencies.length === 1 ? currencies[0]! : ''
}

export function missingTaskLabels(draft: AiTaskDraft): string[] {
  const fields: Array<[string, unknown]> = [
    ['生产任务单号', draft.task_number], ['下单日期', draft.order_date], ['交期', draft.delivery_date],
    ['业务员', draft.salesperson_id], ['生产跟单员', draft.follower_ids.length ? true : null],
    ['订单误差', draft.order_tolerance_percent], ['是否返单', draft.is_repeat_order],
    ['产前确认样', draft.preproduction_sample_required], ['交货方式', draft.delivery_method],
  ]
  return fields.filter(([, value]) => value === '' || value === null || value === undefined).map(([label]) => label)
}

export function validateTaskDraft(draft: AiTaskDraft, options: ProductionTaskOptions): void {
  const missing = missingTaskLabels(draft)
  if (missing.length) throw new Error(`请补齐：${missing.join('、')}。`)
  if (!/^HT[0-9]+(?:-[0-9]+)*$/.test(draft.task_number) || draft.task_number.length > 50) throw new Error('生产任务单号须为 HT 加数字，可用连字符连接数字。')
  const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
  if (!validDate(draft.order_date) || !validDate(draft.delivery_date) || draft.delivery_date < draft.order_date) throw new Error('请填写有效下单日期及不早于下单日期的交期。')
  if (!options.salespeople.some(row => row.id === draft.salesperson_id)) throw new Error('请选择有效业务员。')
  if (!draft.follower_ids.every(id => options.employees.some(row => row.id === id))) throw new Error('请选择有效生产跟单员。')
  if (draft.includes_tax && draft.tax_rate !== null && ![3, 5, 7].includes(Number(draft.tax_rate))) throw new Error('税率须为 3%、5% 或 7%；未知可留待补充。')
  if (!/^\d+(\.\d{1,2})?$/.test(draft.order_tolerance_percent) || Number(draft.order_tolerance_percent) > 100) throw new Error('订单误差必须为 0 到 100，最多两位小数。')
  if (!['SINGLE', 'SPLIT'].includes(draft.delivery_method)) throw new Error('请选择交货方式。')
  if (Boolean(draft.planned_start_date) !== Boolean(draft.planned_end_date) || draft.planned_start_date && (!validDate(draft.planned_start_date) || !validDate(draft.planned_end_date || '') || draft.planned_end_date! < draft.planned_start_date)) throw new Error('计划开始和完工须同时填写有效日期，完工不能早于开始。')
  for (const value of [draft.freight_amount, draft.other_fee_amount]) if (value !== '' && (!/^\d+(\.\d{1,4})?$/.test(value) || !Number.isFinite(Number(value)))) throw new Error('运费和其他费用须为非负金额，最多四位小数。')
  if (!draft.products.length) throw new Error('识别结果没有产品，请先核对原表。')
  const keys = new Set<string>()
  const detailKeys = new Set<string>()
  draft.products.forEach((row, index) => {
    const label = `第 ${index + 1} 项产品`
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(row.client_key) || keys.has(row.client_key)) throw new Error(`${label}的识别编号无效或重复。`)
    keys.add(row.client_key)
    if (!row.customer_product_name?.trim() || !row.customer_specification?.trim()) throw new Error(`请补齐${label}的名称和规格。`)
    if (!/^[1-9]\d*$/.test(String(row.quantity))) throw new Error(`${label}数量必须是大于 0 的整数。`)
    if (!options.units.some(unit => unit.id === row.unit_id) && !row.product_selection?.draft?.unit_name?.trim()) throw new Error(`请选择${label}的单位。`)
    if (row.unit_price !== '' && (!/^\d+(\.\d{1,4})?$/.test(String(row.unit_price)) || !Number.isFinite(Number(row.unit_price)))) throw new Error(`${label}单价须为非负金额，最多四位小数。`)
    if (row.currency_id && !options.currencies.some(currency => currency.id === row.currency_id)) throw new Error(`请重新选择${label}的币种。`)
    if (row.exchange_rate !== '' && (!/^\d+(\.\d{1,8})?$/.test(row.exchange_rate) || Number(row.exchange_rate) <= 0)) throw new Error(`${label}汇率须为大于0的数值，最多八位小数。`)
    const product = options.products.find(item => item.id === row.product_id)
    if (row.product_id && !product) throw new Error(`请重新选择${label}对应的 ERP 产品。`)
    if (product && row.unit_id !== product.default_unit_id) throw new Error(`${label}的单位与所选 ERP 产品不一致。`)
    if (!row.details?.length || row.details.some(detail => !detail.detail_type.trim())) throw new Error(`请补齐${label}的生产明细类型。`)
    row.details.forEach(detail => {
      if (!detail.client_key || detailKeys.has(detail.client_key)) throw new Error('生产明细编号缺失或重复，请重新核对。')
      detailKeys.add(detail.client_key)
    })
  })
  for (const batch of draft.delivery_batches) {
    if (!/^[1-9]\d*$/.test(batch.quantity) || !validDate(batch.delivery_date)) throw new Error('请补齐有效的交货批次数量及日期。')
    if (batch.product_key && !keys.has(batch.product_key)) throw new Error('交货批次对应的产品不存在，请重新选择。')
    if (batch.carton_quantity && (!/^\d+(\.\d{1,4})?$/.test(batch.carton_quantity) || Number(batch.carton_quantity) <= 0)) throw new Error('交货批次箱数须为大于0的数值。')
  }
  if (draft.delivery_method === 'SPLIT' && !draft.delivery_batches.length) throw new Error('请补齐分批交货明细。')
}

export function taskPayload(draft: AiTaskDraft, options: ProductionTaskOptions): AiTaskCreatePayload {
  validateTaskDraft(draft, options)
  return { ...structuredClone(draft), currency_id: draft.currency_id || null, order_source: draft.is_repeat_order ? 'REPEAT' : 'NEW', order_number: draft.task_number,
    includes_tax: draft.includes_tax, is_repeat_order: draft.is_repeat_order!, preproduction_sample_required: draft.preproduction_sample_required!,
    delivery_method: draft.delivery_method as 'SINGLE' | 'SPLIT', tax_rate: draft.includes_tax ? draft.tax_rate : null,
    freight_amount: draft.freight_amount || null, other_fee_amount: draft.other_fee_amount || null,
    delivery_batches: draft.delivery_batches.map(batch => {
      const product = draft.products.find(row => row.client_key === batch.product_key)
      const note = [batch.product_key && `产品：${product?.customer_product_name || batch.product_key}（${batch.product_key}）`,
        batch.color && `颜色：${batch.color}`, batch.packaging_method && `包装：${batch.packaging_method}`,
        batch.carton_quantity && `箱数：${batch.carton_quantity}`, batch.note].filter(Boolean).join('；')
      if (note.length > 500) throw new Error('交货批次说明超过500字，请核对后精简。')
      return { quantity: batch.quantity, delivery_date: batch.delivery_date, note }
    }),
    products: draft.products.map(({ source_currency: _currency, source_item_number: _itemNumber, source_color_card: _colorCard, ...row }) => ({
      ...structuredClone(row), currency_id: row.currency_id || null, unit_price: row.unit_price || null,
      exchange_rate: options.currencies.find(item => item.id === row.currency_id)?.code === 'CNY' ? '1.00000000' : row.exchange_rate || null,
      details: row.details.map(({ source_note: _note, ...detail }) => ({ ...detail })),
    })),
  }
}
