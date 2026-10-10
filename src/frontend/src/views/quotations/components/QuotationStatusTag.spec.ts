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
    expect(source).toContain('color: #faf9f5')
    expect(source).toContain('background: #c96442')
    expect(source).toContain('background: #3898ec')
    expect(source).toContain('background: #4f7d4b')
    expect(source).toContain('background: #b8781e')
    expect(source).toContain('background: #b53333')
    expect(source).toContain('background: #5e5d59')
    expect(source).not.toContain('is-soft')
  })
})
