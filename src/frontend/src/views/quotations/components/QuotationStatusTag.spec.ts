import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import QuotationStatusTag from './QuotationStatusTag.vue'

describe('QuotationStatusTag', () => {
  it('使用报价设计规范的 Strong 成功标签', () => {
    const wrapper = mount(QuotationStatusTag, {
      props: { tone: 'success' },
      slots: { default: '已接受' },
    })

    expect(wrapper.text()).toBe('已接受')
    expect(wrapper.classes()).toEqual(expect.arrayContaining(['quotation-status-tag', 'is-success', 'is-strong']))
  })

  it('草稿状态同样使用 Strong 中性标签', () => {
    const wrapper = mount(QuotationStatusTag, {
      props: { tone: 'neutral' },
      slots: { default: '草稿' },
    })

    expect(wrapper.classes()).toEqual(expect.arrayContaining(['is-neutral', 'is-strong']))
  })

  it('固化 Strong 标签的尺寸、字色和六种语义色', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/quotations/components/QuotationStatusTag.vue'), 'utf8').toLowerCase()

    expect(source).toContain('min-width: 56px')
    expect(source).toContain('height: 24px')
    expect(source).toContain('border-radius: 999px')
    expect(source).toContain('color: var(--erp-tag-neutral-text)')
    expect(source).toContain('background: var(--erp-tag-brand-background)')
    expect(source).toContain('background: var(--erp-tag-info-background)')
    expect(source).toContain('background: var(--erp-tag-success-background)')
    expect(source).toContain('background: var(--erp-tag-warning-background)')
    expect(source).toContain('background: var(--erp-tag-danger-background)')
    expect(source).toContain('background: var(--erp-tag-neutral-background)')
    expect(source).not.toContain('is-soft')
  })
})
