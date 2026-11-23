import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElOption, ElSelect } from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'

import BomCreateView from './BomCreateView.vue'

const api = vi.hoisted(() => ({ fetchBomOptions: vi.fn(), fetchBoms: vi.fn(), createBom: vi.fn() }))
vi.mock('@/api/boms', () => api)
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { method: 'COPY', production_task_product_id: 'target-navy' } }),
  useRouter: () => ({ push: vi.fn() }),
}))

const black = {
  id: 'source-black', bom_number: 'BOM004', production_task_number: 'QA-COPY-01',
  product_catalog_id: 'bed', product_name_snapshot: '测试产品A', product_color_snapshot: '黑色',
  product_unit_name: '把', order_quantity: '400.0000', source_quantity: '380',
  status: 'VERIFIED', status_display: '已确认', version_number: 1, section_count: 2, line_count: 8,
}
const navy = {
  ...black, id: 'source-navy', bom_number: 'BOM005', product_color_snapshot: '藏青',
  order_quantity: '700.0000', status: 'PENDING_CONFIRMATION', status_display: '待确认',
}
let page: VueWrapper

async function openCopy(batchQuantity: string | null = null, history = [black, navy], catalogId: string | null = 'bed') {
  api.fetchBomOptions.mockResolvedValue({
    production_task_products: [{
      id: 'target-navy', product_catalog_id: catalogId, task_number: 'QA-COPY-01', task_etag: 'task-etag',
      product_name: '测试产品A', product_code: 'BED', order_quantity: '700',
      batch_quantity: batchQuantity, existing_bom_count: 0,
    }],
    history_boms: history,
  })
  api.createBom.mockResolvedValue({ id: 'created-bom', bom_number: 'BOM006' })
  page = mount(BomCreateView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return page.getComponent(ElSelect)
}

async function reviewBlack(batchQuantity: string | null = null) {
  const select = await openCopy(batchQuantity)
  await select.findAllComponents(ElOption)[0]!.trigger('click')
  await page.get('.wizard-actions .el-button--primary').trigger('click')
}

afterEach(() => {
  page?.unmount()
  vi.clearAllMocks()
})

it('用生产任务单、产品颜色数量和BOM状态区分来源，并在确认页显示同一选择', async () => {
  const select = await openCopy()
  const choices = select.findAllComponents(ElOption)
  expect(choices.map(option => option.text())).toEqual([
    'QA-COPY-01 · 测试产品A · 黑色 · 400 把 · 已确认',
    'QA-COPY-01 · 测试产品A · 藏青 · 700 把 · 待确认',
  ])
  await choices[1]!.trigger('click')
  await page.get('.wizard-actions .el-button--primary').trigger('click')
  expect(page.get('.review-meta').text()).toContain(choices[1]!.props('label'))
  expect(page.get('.review-meta').text()).not.toContain(navy.bom_number)
})

it('任务、产品、数量和状态都相同时才显示版本，并保留到确认页', async () => {
  const secondVersion = { ...black, id: 'source-black-v2', version_number: 2 }
  const select = await openCopy(null, [black, secondVersion, navy])
  const choices = select.findAllComponents(ElOption)
  expect(choices.map(option => option.text())).toEqual([
    'QA-COPY-01 · 测试产品A · 黑色 · 400 把 · V1 · 已确认',
    'QA-COPY-01 · 测试产品A · 黑色 · 400 把 · V2 · 已确认',
    'QA-COPY-01 · 测试产品A · 藏青 · 700 把 · 待确认',
  ])
  await choices[1]!.trigger('click')
  await page.get('.wizard-actions .el-button--primary').trigger('click')
  expect(page.get('.review-meta').text()).toContain('400 把 · V2 · 已确认')
})

it('仅历史数量不同也能用原BOM创建目标产品草稿', async () => {
  await reviewBlack()
  const row = page.get('.quantity-table').findAll('tbody tr').find(item => item.text().includes('历史'))
  expect(row?.text()).toContain('400')
  expect(row?.text()).toMatch(/少\s*300/)
  const create = page.get('button.el-button--primary')
  expect(create.attributes('disabled')).toBeUndefined()
  await create.trigger('click')
  expect(api.createBom).toHaveBeenCalledWith(expect.objectContaining({
    productionTaskProductId: 'target-navy', sourceBomId: black.id, quantityDifferenceReason: '',
  }))
})

it('本次任务的批次数量也不一致时，须填说明才可创建', async () => {
  await reviewBlack('650')
  const create = page.get('button.el-button--primary')
  expect(create.attributes('disabled')).toBeDefined()
  await page.get('.reason-field input').setValue('本次按任务 700 把执行')
  expect(create.attributes('disabled')).toBeUndefined()
  await create.trigger('click')
  expect(api.createBom).toHaveBeenCalledWith(expect.objectContaining({
    quantityDifferenceReason: '本次按任务 700 把执行',
  }))
})

it('未关联产品也能按生产任务单搜索较早的不同产品 BOM，并带到创建草稿', async () => {
  const olderBom = { ...black, id: 'older-bom', production_task_number: 'QA-OLD-182', product_catalog_id: 'chair', product_name_snapshot: '旧款椅' }
  api.fetchBoms.mockResolvedValue({ data: [olderBom], meta: { total: 1 } })

  const select = await openCopy(null, [black], null)
  expect(select.findAllComponents(ElOption).map(option => option.props('value'))).toEqual([black.id])
  await select.get('input').setValue('qa-old')
  await vi.waitFor(() => expect(api.fetchBoms).toHaveBeenCalledWith(expect.objectContaining({ q: 'qa-old' })))
  await flushPromises()
  const choices = select.findAllComponents(ElOption)
  expect(choices.map(option => option.props('value'))).toEqual([olderBom.id])
  await choices[0]!.trigger('click')
  await page.get('.wizard-actions .el-button--primary').trigger('click')
  expect(page.get('.review-meta').text()).toContain('QA-OLD-182 · 旧款椅')
  await page.get('button.el-button--primary').trigger('click')
  expect(api.createBom).toHaveBeenCalledWith(expect.objectContaining({
    productionTaskProductId: 'target-navy', sourceBomId: olderBom.id,
  }))
})
