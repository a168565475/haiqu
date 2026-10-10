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
      source_version: 'UN M49 2026-08-26 / ISO 3166-1', description: '', extra_data: {},
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

  it('展示九类真实数量、标准来源和国家标准字段', async () => {
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('基础资料中心')
    expect(wrapper.text()).toContain('国家 / 地区249')
    expect(wrapper.text()).toContain('币种178')
    expect(wrapper.text()).toContain('Incoterms11')
    expect(wrapper.text()).toContain('标准来源5')
    expect(wrapper.text()).toContain('公司本位币未配置')
    expect(wrapper.text()).toContain('CN')
    expect(wrapper.text()).toContain('CHN')
    expect(wrapper.text()).toContain('ISO 3166')
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

  it('汇率为空且未配置本位币时明确禁止自动折算', async () => {
    const wrapper = mount(MasterDataCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const exchangeButton = wrapper.findAll('button').find((button) => button.text().includes('汇率'))
    expect(exchangeButton).toBeTruthy()
    await exchangeButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('暂无汇率历史')
    expect(wrapper.text()).toContain('不会自动折算或展示本位币金额')
    expect(wrapper.text()).toContain('仍可人工新增汇率历史')
  })
})
