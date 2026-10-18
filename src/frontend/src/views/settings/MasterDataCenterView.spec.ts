import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
      chinese_name: '中国', english_name: 'China', status: 'ACTIVE', sort_order: 0,
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

describe('MasterDataCenterView', () => {
  beforeEach(() => {
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
})
