import { describe, expect, it } from 'vitest'

import type { CustomerDetail, CustomerOptions } from '@/types/customer'

import {
  buildCustomerCreatePayload,
  createEmptyCustomerForm,
  getDerivedCountryCode,
  isValidContactMethod,
  isValidWebsite,
  mapCustomerToForm,
  validateCustomerCreateForm,
  validateCustomerEditForm,
} from './customerForm'

const options: CustomerOptions = {
  lifecycle_stages: [{ item_code: 'LEAD', display_name: '线索客户' }],
  activity_statuses: [],
  customer_grades: [{ id: 'grade-a', item_code: 'A', display_name: 'A级', description: '' }],
  customer_types: [{ id: 'type-brand', item_code: 'BRAND', display_name: '品牌客户', description: '' }],
  customer_sources: [{ id: 'source-ispo', item_code: 'ISPO', display_name: 'ISPO 展会', description: '' }],
  industries: [],
  interested_products: [],
  primary_regions: [{ id: 'europe', legacy_selector_code: 'EU', legacy_tree_code: 'EU', region_name: '欧洲' }],
  secondary_regions: [{ id: 'de', parent_id: 'europe', country_code: 'DE', legacy_selector_code: 'DE', legacy_tree_code: 'EU-DE', region_name: '德国' }],
  customer_tags: [],
  owner_options: [],
  country_options: [],
}

describe('customerForm', () => {
  it('校验新建客户必填字段与联系方式边界', () => {
    const form = createEmptyCustomerForm()
    expect(validateCustomerCreateForm(form)).toMatchObject({
      accountName: '请输入客户名称。',
      primaryRegionId: '请选择一级地区。',
      sourceId: '请选择客户来源。',
    })

    Object.assign(form, {
      accountName: 'Aurora Outdoor GmbH',
      primaryRegionId: 'europe',
      sourceId: 'source-ispo',
      contactMethod: 'anna@example.com',
    })
    expect(validateCustomerCreateForm(form).contactName).toBeTruthy()
    form.contactName = 'Anna'
    expect(validateCustomerCreateForm(form)).toEqual({})
  })

  it('识别网站、邮箱和电话号码格式', () => {
    expect(isValidWebsite('aurora-outdoor.de')).toBe(true)
    expect(isValidWebsite('https://aurora-outdoor.de')).toBe(true)
    expect(isValidWebsite('://bad')).toBe(false)
    expect(isValidContactMethod('anna@aurora-outdoor.de')).toBe(true)
    expect(isValidContactMethod('+49 40 8892 1870')).toBe(true)
    expect(isValidContactMethod('abc')).toBe(false)
  })

  it('按二级地区生成真实国家代码与创建请求', () => {
    const form = createEmptyCustomerForm()
    Object.assign(form, {
      accountName: 'Aurora Outdoor GmbH',
      primaryRegionId: 'europe',
      secondaryRegionId: 'de',
      sourceId: 'source-ispo',
      contactName: 'Anna',
      contactMethod: 'anna@aurora-outdoor.de',
    })
    expect(getDerivedCountryCode(options, 'de')).toBe('DE')
    expect(buildCustomerCreatePayload(form, options)).toMatchObject({
      account_name: 'Aurora Outdoor GmbH',
      primary_country_code: 'DE',
      customer_source_item_id: 'source-ispo',
      contact_method_type: 'EMAIL',
    })
  })

  it('编辑回填安全处理 null 与缺失关联对象', () => {
    const customer = {
      id: 'customer-1',
      account_code: 'CUS-0001',
      account_name: 'Aurora',
      english_name: '',
      short_name: '',
      lifecycle_stage: 'LEAD',
      lifecycle_stage_display: '线索客户',
      primary_country_code: '',
      primary_region: null,
      secondary_region: null,
      industry: null,
      inquiry_keywords: '',
      recorded_by: null,
      recorded_at: null,
      primary_owner: null,
      attention_level: null,
      customer_grade: null,
      first_source: null,
      latest_source: null,
      customer_types: [],
      customer_tags: [],
      activity: null,
      last_contact_at: null,
      next_follow_up_at: null,
      customer_value: null,
      lifetime_sales_amount: null,
      lifetime_sales_order_count: null,
      last_12m_sales_amount: null,
      last_12m_sales_order_count: null,
      quotation_conversion_rate: null,
      recent_order: null,
      archived_at: null,
      created_at: '',
      updated_at: '',
      primary_website_url: '',
      source_system: '',
      external_id: '',
      notes: '',
      legacy_source_data: {},
      archive_reason: '',
      current_assignments: [],
      business_snapshot: null,
      interested_products: [],
      company_contact_methods: [],
    } as CustomerDetail
    expect(() => mapCustomerToForm(customer, options)).not.toThrow()
    expect(mapCustomerToForm(customer, options)).toMatchObject({
      accountName: 'Aurora',
      primaryRegionId: '',
      gradeId: '',
      addressLabel: '办公地址',
      addressLine1: '',
    })
  })

  it('编辑页阻止来源字段不成对和不完整地址', () => {
    const form = createEmptyCustomerForm()
    Object.assign(form, {
      accountName: 'Aurora',
      primaryRegionId: 'europe',
      sourceId: 'source-ispo',
      gradeId: 'grade-a',
      typeIds: ['type-brand'],
      sourceSystem: 'ERP',
      city: 'Hamburg',
      taxIdentifier: 'DE123',
    })
    expect(validateCustomerEditForm(form)).toMatchObject({
      externalId: expect.any(String),
      addressLine1: expect.any(String),
      addressCountryCode: expect.any(String),
      entityLegalName: expect.any(String),
    })
  })
})
