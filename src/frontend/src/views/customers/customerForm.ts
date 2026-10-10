import { AxiosError } from 'axios'

import type {
  CustomerAddress,
  CustomerCreateInput,
  CustomerDetail,
  CustomerEntity,
  CustomerOptions,
  CustomerUpdateInput,
} from '@/types/customer'

export interface CustomerFormModel {
  accountName: string
  englishName: string
  shortName: string
  lifecycleStage: CustomerDetail['lifecycle_stage']
  countryCode: string
  website: string
  primaryRegionId: string
  secondaryRegionId: string
  sourceId: string
  gradeId: string
  typeIds: string[]
  tagIds: string[]
  industryId: string
  interestedProductIds: string[]
  inquiryKeywords: string
  sourceSystem: string
  externalId: string
  notes: string
  contactName: string
  contactMethod: string
  entityLegalName: string
  entityEnglishName: string
  registrationNumber: string
  taxIdentifier: string
  addressCountryCode: string
  addressLabel: string
  stateProvince: string
  city: string
  postalCode: string
  addressLine1: string
  addressLine2: string
  recipientName: string
  recipientPhone: string
}

export type CustomerFormErrors = Partial<Record<keyof CustomerFormModel, string>>

export function createEmptyCustomerForm(): CustomerFormModel {
  return {
    accountName: '',
    englishName: '',
    shortName: '',
    lifecycleStage: 'LEAD',
    countryCode: '',
    website: '',
    primaryRegionId: '',
    secondaryRegionId: '',
    sourceId: '',
    gradeId: '',
    typeIds: [],
    tagIds: [],
    industryId: '',
    interestedProductIds: [],
    inquiryKeywords: '',
    sourceSystem: '',
    externalId: '',
    notes: '',
    contactName: '',
    contactMethod: '',
    entityLegalName: '',
    entityEnglishName: '',
    registrationNumber: '',
    taxIdentifier: '',
    addressCountryCode: '',
    addressLabel: '办公地址',
    stateProvince: '',
    city: '',
    postalCode: '',
    addressLine1: '',
    addressLine2: '',
    recipientName: '',
    recipientPhone: '',
  }
}

export function getSecondaryRegions(options: CustomerOptions | null, primaryRegionId: string) {
  return options?.secondary_regions.filter((item) => item.parent_id === primaryRegionId) || []
}

export function getDerivedCountryCode(options: CustomerOptions | null, secondaryRegionId: string): string {
  return options?.secondary_regions.find((item) => item.id === secondaryRegionId)?.country_code || ''
}

export function isValidWebsite(value: string): boolean {
  const trimmed = value.trim()
  if (!trimmed) return true
  try {
    const parsed = new URL(trimmed.includes('://') ? trimmed : `https://${trimmed}`)
    return ['http:', 'https:'].includes(parsed.protocol) && Boolean(parsed.hostname)
  } catch {
    return false
  }
}

export function resolveContactMethodType(value: string): 'EMAIL' | 'PHONE' {
  return value.includes('@') ? 'EMAIL' : 'PHONE'
}

export function isValidContactMethod(value: string): boolean {
  const trimmed = value.trim()
  if (!trimmed) return true
  if (resolveContactMethodType(trimmed) === 'EMAIL') {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)
  }
  return /^[+\d][\d\s()+-]{5,30}$/.test(trimmed)
}

export function validateCustomerCreateForm(form: CustomerFormModel): CustomerFormErrors {
  const errors: CustomerFormErrors = {}
  if (!form.accountName.trim()) errors.accountName = '请输入客户名称。'
  else if (form.accountName.trim().length > 250) errors.accountName = '客户名称不能超过 250 个字符。'
  if (!form.primaryRegionId) errors.primaryRegionId = '请选择一级地区。'
  if (!form.sourceId) errors.sourceId = '请选择客户来源。'
  if (!isValidWebsite(form.website)) errors.website = '请输入有效的网站地址或域名。'
  if (form.contactMethod.trim() && !form.contactName.trim()) {
    errors.contactName = '填写联系方式时必须同时填写联系人姓名。'
  }
  if (!isValidContactMethod(form.contactMethod)) {
    errors.contactMethod = '请输入有效的邮箱或电话号码。'
  }
  return errors
}

export function validateCustomerEditForm(form: CustomerFormModel): CustomerFormErrors {
  const errors: CustomerFormErrors = {}
  if (!form.accountName.trim()) errors.accountName = '请输入客户名称。'
  else if (form.accountName.trim().length > 250) errors.accountName = '客户名称不能超过 250 个字符。'
  if (!form.primaryRegionId) errors.primaryRegionId = '请选择一级地区。'
  if (!form.typeIds.length) errors.typeIds = '请选择至少一种客户类型。'
  if (!form.sourceId) errors.sourceId = '请选择客户来源。'
  if (!form.gradeId) errors.gradeId = '请选择客户等级。'
  if (!isValidWebsite(form.website)) errors.website = '请输入有效的网站地址或域名。'
  if (Boolean(form.sourceSystem.trim()) !== Boolean(form.externalId.trim())) {
    errors.sourceSystem = '来源系统和外部编号必须同时填写或同时留空。'
    errors.externalId = '来源系统和外部编号必须同时填写或同时留空。'
  }
  const hasAddress = [
    form.addressLine1,
    form.stateProvince,
    form.city,
    form.postalCode,
    form.recipientName,
    form.recipientPhone,
  ].some((item) => item.trim())
  const hasEntity = [form.entityEnglishName, form.registrationNumber, form.taxIdentifier]
    .some((item) => item.trim())
  if (hasEntity && !form.entityLegalName.trim()) errors.entityLegalName = '填写主体登记资料前请填写法定主体名称。'
  if (hasAddress && !form.addressLine1.trim()) errors.addressLine1 = '请输入详细地址。'
  if (hasAddress && !form.addressCountryCode) errors.addressCountryCode = '请选择国家或地区。'
  if (hasAddress && !form.entityLegalName.trim()) errors.entityLegalName = '保存地址前请填写法定主体名称。'
  return errors
}

export function buildCustomerCreatePayload(
  form: CustomerFormModel,
  options: CustomerOptions | null,
): CustomerCreateInput {
  const contactMethod = form.contactMethod.trim()
  const payload: CustomerCreateInput = {
    account_name: form.accountName.trim(),
    primary_country_code: getDerivedCountryCode(options, form.secondaryRegionId),
    primary_region_id: form.primaryRegionId,
    secondary_region_id: form.secondaryRegionId || null,
    customer_source_item_id: form.sourceId,
    primary_website_url: form.website.trim() || undefined,
    contact_name: form.contactName.trim() || undefined,
  }
  if (contactMethod) {
    payload.contact_method_type = resolveContactMethodType(contactMethod)
    payload.contact_method_value = contactMethod
  }
  return payload
}

export function buildCustomerUpdatePayload(
  form: CustomerFormModel,
  options: CustomerOptions | null,
): CustomerUpdateInput {
  return {
    account_name: form.accountName.trim(),
    english_name: form.englishName.trim(),
    short_name: form.shortName.trim(),
    lifecycle_stage: form.lifecycleStage,
    primary_country_code: getDerivedCountryCode(options, form.secondaryRegionId) || form.countryCode,
    primary_region_id: form.primaryRegionId,
    secondary_region_id: form.secondaryRegionId || null,
    primary_website_url: form.website.trim(),
    inquiry_keywords: form.inquiryKeywords.trim(),
    industry_item_id: form.industryId || null,
    interested_product_item_ids: [...form.interestedProductIds],
    source_system: form.sourceSystem.trim(),
    external_id: form.externalId.trim(),
    notes: form.notes.trim(),
  }
}

export function mapCustomerToForm(
  customer: CustomerDetail,
  options: CustomerOptions,
  entity?: CustomerEntity,
  address?: CustomerAddress,
): CustomerFormModel {
  const form = createEmptyCustomerForm()
  form.accountName = customer.account_name || ''
  form.englishName = customer.english_name || ''
  form.shortName = customer.short_name || ''
  form.lifecycleStage = customer.lifecycle_stage || 'LEAD'
  form.countryCode = customer.primary_country_code || ''
  form.website = customer.primary_website_url || ''
  form.primaryRegionId = customer.primary_region?.id || ''
  form.secondaryRegionId = customer.secondary_region?.id || ''
  form.sourceId = options.customer_sources.find((item) => item.item_code === customer.latest_source?.item_code)?.id || ''
  form.gradeId = options.customer_grades.find((item) => item.item_code === customer.customer_grade?.item_code)?.id || ''
  form.typeIds = customer.customer_types.flatMap((current) => {
    const option = options.customer_types.find((item) => item.item_code === current.item_code)
    return option ? [option.id] : []
  })
  form.tagIds = customer.customer_tags.map((item) => item.id)
  form.industryId = customer.industry?.id || ''
  form.interestedProductIds = customer.interested_products.map((item) => item.product_item_id)
  form.inquiryKeywords = customer.inquiry_keywords || ''
  form.sourceSystem = customer.source_system || ''
  form.externalId = customer.external_id || ''
  form.notes = customer.notes || ''
  form.entityLegalName = entity?.legal_name || ''
  form.entityEnglishName = entity?.english_legal_name || ''
  form.registrationNumber = entity?.registration_number || ''
  form.taxIdentifier = entity?.tax_identifier || ''
  form.addressCountryCode = address?.country_code || customer.primary_country_code || ''
  form.addressLabel = address?.label || '办公地址'
  form.stateProvince = address?.state_province || ''
  form.city = address?.city || ''
  form.postalCode = address?.postal_code || ''
  form.addressLine1 = address?.address_line1 || ''
  form.addressLine2 = address?.address_line2 || ''
  form.recipientName = address?.recipient_name || ''
  form.recipientPhone = address?.recipient_phone || ''
  return form
}

export function customerFormSnapshot(form: CustomerFormModel): string {
  return JSON.stringify({
    ...form,
    typeIds: [...form.typeIds].sort(),
    tagIds: [...form.tagIds].sort(),
    interestedProductIds: [...form.interestedProductIds].sort(),
  })
}

export function customerRequestError(error: unknown, fallback = '请求失败，请稍后重试。'): string {
  if (!(error instanceof AxiosError)) return fallback
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const body = error.response.data as {
    error?: { message?: string; field_errors?: Record<string, string[]> }
  }
  const firstFieldError = body.error?.field_errors
    ? Object.values(body.error.field_errors).flat()[0]
    : undefined
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有执行该操作的权限。'
  if (error.response.status === 404) return '客户不存在或已被删除。'
  if (error.response.status === 409) return '当前资料与已有记录冲突，请检查后重试。'
  if (error.response.status === 412) return '客户资料已被其他人修改，请刷新后重试。'
  if (error.response.status === 428) return '缺少并发版本信息，请刷新页面后重试。'
  if (error.response.status >= 500) return '后端服务异常，请稍后重试。'
  return firstFieldError || body.error?.message || fallback
}

export function formatCustomerDateTime(value: string | null | undefined): string {
  if (!value) return '未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间异常'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}
