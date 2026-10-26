import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { AxiosError } from 'axios'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchAllMasterDataRecords, fetchMasterDataSummary } from '@/api/referenceData'
import type { MasterDataRecord, MasterDataSummary } from '@/types/referenceData'

import MasterDataCenterView from './MasterDataCenterView.vue'

const fixtures = vi.hoisted(() => ({
  granted: new Set<string>(),
  summary: {
    category_counts: {
      countries: 249, currencies: 178, exchange_rates: 0, units: 0, incoterms: 11,
      payment_methods: 0, transport_methods: 0, ports: 0, couriers: 0,
    },
    standard_source_count: 5,
    standard_sources: ['ISO 3166', 'ISO 4217', 'UN/CEFACT Rec.20', 'ICC 2020', 'UN/LOCODE'],
    base_currency: null,
    config_version: 1,
  },
  countries: [
    {
      id: 'country-cn', code: 'CN', alpha3_code: 'CHN', numeric_code: '156',
      chinese_name: '中国', english_name: 'China', status: 'ACTIVE' as const, sort_order: 0,
      source_version: 'UN M49 2026-08-26 / ISO 3166-1', description: '',
      extra_data: { region_name: 'Asia' },
      created_at: '2026-08-26T00:00:00Z', updated_at: '2026-08-26T00:00:00Z', archived_at: null,
    },
  ],
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { is_superuser: false },
    hasPermission: (permission: string) => fixtures.granted.has(permission),
  }),
}))

vi.mock('@/api/referenceData', () => ({
  fetchMasterDataSummary: vi.fn().mockImplementation(() => Promise.resolve(fixtures.summary)),
  fetchMasterDataList: vi.fn().mockImplementation((resource: string) => Promise.resolve(
    resource === 'countries'
      ? { data: fixtures.countries, meta: { page: 1, page_size: 10, total: 249, total_pages: 25 } }
      : { data: [], meta: { page: 1, page_size: 10, total: 0, total_pages: 0 } },
  )),
  fetchAllMasterDataRecords: vi.fn().mockImplementation((resource: string) => Promise.resolve(
    resource === 'countries' ? fixtures.countries : [],
  )),
  fetchMasterDataRecord: vi.fn(),
  createMasterDataRecord: vi.fn(),
  updateMasterDataRecord: vi.fn(),
  changeMasterDataStatus: vi.fn(),
  archiveMasterDataRecord: vi.fn(),
  correctExchangeRate: vi.fn(),
}))

enableAutoUnmount(afterEach)

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function apiFailure(status: number) {
  return new AxiosError('请求失败', undefined, undefined, undefined, {
    status, data: { error: { message: '当前请求失败' } }, statusText: '', headers: {}, config: {} as never,
  })
}

function pageState(wrapper: VueWrapper) {
  return (wrapper.vm.$ as unknown as { setupState: {
    loading: boolean; records: MasterDataRecord[]; summary: MasterDataSummary; loadError: string; permissionDenied: boolean
  } }).setupState
}

async function selectCategory(wrapper: VueWrapper, label: string) {
  await wrapper.findAll('.category-item').find(button => button.text().startsWith(label))!.trigger('click')
}

describe('MasterDataCenterView', () => {
  beforeEach(() => {
    vi.mocked(fetchMasterDataSummary).mockReset().mockResolvedValue(fixtures.summary)
    vi.mocked(fetchAllMasterDataRecords).mockReset().mockImplementation(async resource => resource === 'countries' ? fixtures.countries : [])
    fixtures.granted.clear()
    for (const model of ['country', 'currency', 'exchangerate', 'unit', 'incoterm', 'paymentmethod', 'transportmethod', 'port', 'courier']) {
      fixtures.granted.add(`reference_data.view_${model}`)
    }
  })

  it('移除重复层级并展示国家国旗与洲别', async () => {
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('基础资料中心')
    expect(wrapper.text()).toContain('国家 / 地区249')
    expect(wrapper.text()).toContain('币种178')
    expect(wrapper.text()).toContain('Incoterms11')
    expect(wrapper.text()).toContain('CN')
    expect(wrapper.text()).toContain('CHN')
    expect(wrapper.text()).toContain('亚洲')
    expect(wrapper.find('.page-breadcrumb').exists()).toBe(false)
    expect(wrapper.find('.page-heading p').exists()).toBe(false)
    expect(wrapper.find('.metric-grid').exists()).toBe(false)
    expect(wrapper.find('.standards-card').exists()).toBe(false)
    expect(wrapper.find('[data-testid="country-flag"]').attributes('src')).toBe('https://flagcdn.com/24x18/cn.png')
    expect(wrapper.find('[data-testid="country-flag"]').attributes('alt')).toBe('中国国旗')
    expect(wrapper.find('.data-card__header .settings-tag').exists()).toBe(false)
    expect(wrapper.findAll('.data-card__header button').map(button => button.text())).toEqual(['导出数据'])
  })

  it('没有任一基础资料查看权限时显示独立无权限状态且不请求汇总', async () => {
    fixtures.granted.clear()
    const { fetchMasterDataSummary } = await import('@/api/referenceData')
    vi.mocked(fetchMasterDataSummary).mockClear()

    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('无配置权限')
    expect(wrapper.text()).toContain('联系管理员')
    expect(fetchMasterDataSummary).not.toHaveBeenCalled()
  })

  it('嵌入时移除筛选卡和导出，洲别按钮筛选整份国家资料并可恢复全部', async () => {
    const { fetchAllMasterDataRecords } = await import('@/api/referenceData')
    vi.mocked(fetchAllMasterDataRecords).mockResolvedValueOnce([
      fixtures.countries[0]!,
      { ...fixtures.countries[0]!, id: 'country-fr', code: 'FR', chinese_name: '法国', extra_data: { region_name: 'Europe' } },
    ])
    const wrapper = mount(MasterDataCenterView, { props: { embedded: true }, global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.find('[aria-label="基础资料筛选"]').exists()).toBe(false)
    expect(wrapper.find('h1').exists()).toBe(false)
    expect(wrapper.findAll('button').some(button => button.text() === '导出数据')).toBe(false)
    const choices = wrapper.get('[aria-label="洲别筛选"]')
    await choices.findAll('button').find(button => button.text() === '欧洲')!.trigger('click')
    expect(wrapper.get('[data-testid="master-data-table"]').text()).toContain('法国')
    expect(wrapper.get('[data-testid="master-data-table"]').text()).not.toContain('中国')
    await choices.findAll('button').find(button => button.text() === '全部')!.trigger('click')
    expect(wrapper.get('[data-testid="master-data-table"]').text()).toContain('中国')
    expect(wrapper.get('[data-testid="master-data-table"]').text()).toContain('法国')
    wrapper.unmount()
  })

  it('汇率为空时区分生产人民币换算和公司本位币配置', async () => {
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const exchangeButton = wrapper.findAll('button').find((button) => button.text().includes('汇率'))
    expect(exchangeButton).toBeTruthy()
    await exchangeButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('暂无汇率历史')
    expect(wrapper.text()).toContain('可人工维护外币兑人民币汇率')
    expect(wrapper.text()).toContain('不影响生产任务的人民币换算')
  })

  it('嵌入配置窗口时不直接销毁尚未处理的基础资料编辑', async () => {
    fixtures.granted.add('reference_data.add_country')
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus], stubs: { teleport: true, ElSelect: true, ElOption: true } } })
    await flushPromises()
    expect(wrapper.vm.canClose()).toBe(true)
    await wrapper.findAll('button').find(button => button.text() === '新增资料')!.trigger('click')
    await flushPromises()
    expect(wrapper.vm.canClose()).toBe(false)
    await wrapper.findAll('button').find(button => button.text() === '取消')!.trigger('click')
    expect(wrapper.vm.canClose()).toBe(true)
    wrapper.unmount()
  })

  it.each(['success', 'failure', 'forbidden'] as const)('切分类后旧请求 %s 不能覆盖新分类结果', async outcome => {
    const previous = deferred<MasterDataRecord[]>()
    vi.mocked(fetchAllMasterDataRecords).mockReturnValueOnce(previous.promise)
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await selectCategory(wrapper, '币种')
    await flushPromises()
    expect(wrapper.text()).toContain('暂无基础资料')

    if (outcome === 'success') previous.resolve(fixtures.countries)
    else previous.reject(apiFailure(outcome === 'forbidden' ? 403 : 500))
    await flushPromises()

    expect(wrapper.text()).toContain('暂无基础资料')
    expect(wrapper.text()).not.toContain('资料加载失败')
    expect(wrapper.text()).not.toContain('无查看权限')
    expect(pageState(wrapper).records).toEqual([])
  })

  it.each(['success', 'failure', 'forbidden'] as const)('新分类仍在加载时旧请求 %s 不能提前关闭加载状态', async outcome => {
    const previous = deferred<MasterDataRecord[]>()
    const current = deferred<MasterDataRecord[]>()
    vi.mocked(fetchAllMasterDataRecords).mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await selectCategory(wrapper, '币种')
    if (outcome === 'success') previous.resolve(fixtures.countries)
    else previous.reject(apiFailure(outcome === 'forbidden' ? 403 : 500))
    await flushPromises()

    expect(pageState(wrapper).loading).toBe(true)
    expect(pageState(wrapper).records).toEqual([])
    expect(wrapper.text()).not.toContain('无查看权限')
    current.resolve([])
    await flushPromises()
    expect(pageState(wrapper).loading).toBe(false)
    expect(wrapper.text()).toContain('暂无基础资料')
  })

  it('同一分类连续搜索时只显示最新条件的结果', async () => {
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const previous = deferred<MasterDataRecord[]>()
    const current = deferred<MasterDataRecord[]>()
    vi.mocked(fetchAllMasterDataRecords).mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    const search = wrapper.get('input[placeholder="输入名称或编码"]')
    await search.setValue('中国')
    await search.trigger('keyup.enter')
    await search.setValue('法国')
    await search.trigger('keyup.enter')
    expect(fetchAllMasterDataRecords).toHaveBeenLastCalledWith('countries', { q: '法国', status: undefined, source: undefined })
    current.resolve([{ ...fixtures.countries[0]!, id: 'country-fr', code: 'FR', chinese_name: '法国' }])
    await flushPromises()
    previous.resolve(fixtures.countries)
    await flushPromises()
    expect(wrapper.get('[data-testid="master-data-table"]').text()).toContain('法国')
    expect(wrapper.get('[data-testid="master-data-table"]').text()).not.toContain('中国')
  })

  it('切到无权限分类会结束旧列表加载，旧结果不能恢复数据', async () => {
    fixtures.granted.delete('reference_data.view_currency')
    const previous = deferred<MasterDataRecord[]>()
    vi.mocked(fetchAllMasterDataRecords).mockReturnValueOnce(previous.promise)
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await selectCategory(wrapper, '币种')
    expect(pageState(wrapper).loading).toBe(false)
    expect(wrapper.text()).toContain('无查看权限')
    expect(fetchAllMasterDataRecords).toHaveBeenCalledTimes(1)
    previous.resolve(fixtures.countries)
    await flushPromises()
    expect(pageState(wrapper).records).toEqual([])
    expect(wrapper.text()).toContain('无查看权限')
  })

  it.each([500, 403])('当前列表返回 %s 时保留对应错误并结束加载', async status => {
    vi.mocked(fetchAllMasterDataRecords).mockRejectedValueOnce(apiFailure(status))
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain(status === 403 ? '无查看权限' : '资料加载失败')
    expect(pageState(wrapper).loading).toBe(false)
    expect(pageState(wrapper).records).toEqual([])
  })

  it('初次列表先完成时仍等待汇总，汇总结束后才关闭整页加载', async () => {
    const summary = deferred<MasterDataSummary>()
    vi.mocked(fetchMasterDataSummary).mockReturnValueOnce(summary.promise)
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(pageState(wrapper).loading).toBe(true)
    summary.resolve(fixtures.summary)
    await flushPromises()
    expect(pageState(wrapper).loading).toBe(false)
    expect(wrapper.text()).toContain('中国')
  })

  it.each([500, 403])('初次汇总旧请求返回 %s 时不污染新分类或提前结束新列表加载', async status => {
    const summary = deferred<MasterDataSummary>()
    const current = deferred<MasterDataRecord[]>()
    vi.mocked(fetchMasterDataSummary).mockReturnValueOnce(summary.promise)
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    vi.mocked(fetchAllMasterDataRecords).mockReturnValueOnce(current.promise)
    await selectCategory(wrapper, '币种')
    summary.reject(apiFailure(status))
    await flushPromises()
    expect(pageState(wrapper).loading).toBe(true)
    expect(wrapper.text()).not.toContain('资料加载失败')
    expect(wrapper.text()).not.toContain('无查看权限')
    current.resolve([])
    await flushPromises()
    expect(pageState(wrapper).loading).toBe(false)
    expect(wrapper.text()).toContain('暂无基础资料')
  })

  it.each(['success', 'failure', 'forbidden'] as const)('卸载后未完成请求 %s 不再更新页面状态', async outcome => {
    const records = deferred<MasterDataRecord[]>()
    const summary = deferred<MasterDataSummary>()
    vi.mocked(fetchAllMasterDataRecords).mockReturnValueOnce(records.promise)
    vi.mocked(fetchMasterDataSummary).mockReturnValueOnce(summary.promise)
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    const state = pageState(wrapper)
    const initialSummary = state.summary
    wrapper.unmount()
    if (outcome === 'success') records.resolve(fixtures.countries)
    else records.reject(apiFailure(outcome === 'forbidden' ? 403 : 500))
    summary.resolve(fixtures.summary)
    await flushPromises()
    expect(state.records).toEqual([])
    expect(state.summary).toBe(initialSummary)
    expect(state.loadError).toBe('')
    expect(state.permissionDenied).toBe(false)
    expect(state.loading).toBe(false)
  })
})
