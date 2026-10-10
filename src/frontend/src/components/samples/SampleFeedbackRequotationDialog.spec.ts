import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SampleFeedbackRequotationDialog from './SampleFeedbackRequotationDialog.vue'
enableAutoUnmount(afterEach)

const api = vi.hoisted(() => ({
  fetchSampleFeedbackRequotationOptions: vi.fn().mockResolvedValue({
    etag: '"sample-v2"',
    data: [{
      quotation_id: 'quote-1', quotation_number: 'QUO-001', quotation_outcome_status: 'OPEN',
      version_id: 'version-1', version_number: 1, version_status: 'SENT', currency_code: 'USD',
      subject: '折叠椅报价', updated_at: '2026-08-26T08:00:00Z', is_sample_source: true,
      target_mode: 'APPEND_VERSION', target_label: '沿用 QUO-001，生成 V2',
    }],
  }),
  createSampleFeedbackRequotation: vi.fn().mockResolvedValue({
    etag: '"sample-v3"',
    data: {
      quotation_id: 'quote-1', quotation_number: 'QUO-001', quotation_version_id: 'version-2',
      version_number: 2, created_new_quotation: false, replayed: false,
    },
  }),
}))

vi.mock('@/api/samples', () => api)

const feedback = {
  id: 'feedback-1', customer_contact: null, recorded_by: null, feedback_type: 'NEGATIVE', feedback_type_display: '负向',
  feedback_content: '客户要求把椅背高度增加 3 厘米', occurred_at: '2026-08-26T08:00:00Z',
  confirmation_result: 'REJECTED' as const, confirmation_result_display: '确认未通过',
  confirmation_source: 'CUSTOMER' as const, confirmation_source_display: '客户确认', source_object_version: 1,
  rejection_reason: '尺寸不符', corrective_action_request: '椅背高度增加 3 厘米', confirmed_at: '2026-08-26T08:00:00Z',
  requotation_source_version: null, requotation_source_label: '', resulting_quotation_version: null,
  resulting_quotation_id: null, resulting_quotation_label: '', requotation_created_by: null, requotation_created_at: null,
  created_at: '2026-08-26T08:00:00Z',
}

describe('SampleFeedbackRequotationDialog', () => {
  it('加载失败显示重试，重试后恢复同客户报价选择', async () => {
    api.fetchSampleFeedbackRequotationOptions.mockRejectedValueOnce(new Error('历史报价加载失败'))
    const wrapper = mount(SampleFeedbackRequotationDialog, {
      attachTo: document.body,
      props: { modelValue: true, sampleId: 'sample-1', sampleNumber: 'SAM-001', customerName: '测试客户', sampleEtag: '"v1"', feedback, canCreateQuotation: true },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    expect(document.body.querySelector('.requote-error')?.textContent).toContain('历史报价加载失败')
    const retry = wrapper.findAllComponents({ name: 'ElButton' }).find(button => button.text() === '重新加载')!
    await retry.trigger('click'); await flushPromises()
    expect(document.body.querySelector('.requote-error')).toBeNull()
    expect(document.body.querySelector('.quote-options')?.textContent).toContain('QUO-001 V1')
    wrapper.unmount()
  })
  it('关闭后丢弃未完成的历史报价响应，不污染下一次打开', async () => {
    let resolve!: (value: { etag: string; data: never[] }) => void
    api.fetchSampleFeedbackRequotationOptions.mockReturnValueOnce(new Promise(done => { resolve = done }))
    const wrapper = mount(SampleFeedbackRequotationDialog, {
      attachTo: document.body,
      props: { modelValue: true, sampleId: 'sample-1', sampleNumber: 'SAM-001', customerName: '测试客户', sampleEtag: '"v1"', feedback, canCreateQuotation: true },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises(); await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
    resolve({ etag: '"stale"', data: [] }); await flushPromises()
    expect(document.body.querySelector('.quote-options')?.textContent).toContain('QUO-001 V1')
    wrapper.unmount()
  })
  it('展示同客户历史报价并创建可追溯的下一个版本', async () => {
    const wrapper = mount(SampleFeedbackRequotationDialog, {
      attachTo: document.body,
      props: {
        modelValue: false,
        sampleId: 'sample-1',
        sampleNumber: 'SAM-001',
        customerName: '测试客户',
        sampleEtag: '"sample-v2"',
        feedback,
        canCreateQuotation: true,
      },
      global: { plugins: [ElementPlus] },
    })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(document.body.textContent).toContain('客户要求把椅背高度增加 3 厘米')
    expect(document.body.textContent).toContain('QUO-001 V1')
    expect(Array.from(document.body.querySelectorAll('input')).some(
      (input) => input.value === '沿用 QUO-001，生成 V2',
    )).toBe(true)

    const createButton = wrapper.findAllComponents({ name: 'ElButton' })
      .find((button) => button.text().includes('创建报价草稿'))
    expect(createButton).toBeTruthy()
    await createButton!.trigger('click')
    await flushPromises()

    expect(api.createSampleFeedbackRequotation).toHaveBeenCalledWith(
      'sample-1',
      'feedback-1',
      expect.objectContaining({
        source_quotation_version_id: 'version-1',
        valid_until: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        notes: '椅背高度增加 3 厘米',
      }),
      '"sample-v2"',
    )
    expect(wrapper.emitted('created')).toEqual([['quote-1', '"sample-v3"', 'version-2']])
    wrapper.unmount()
  })
})
