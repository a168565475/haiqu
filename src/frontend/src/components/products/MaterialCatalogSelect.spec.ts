import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import MaterialCatalogSelect from './MaterialCatalogSelect.vue'

const options = [
  { value: 'tube', label: '管材' },
  { value: 'disabled', label: '停用类别', disabled: true },
  { value: 'fabric', label: '面料' },
]
let wrapper: VueWrapper | undefined

async function render(props: Record<string, unknown> = {}) {
  wrapper = mount(MaterialCatalogSelect, {
    attachTo: document.body,
    props: { modelValue: 'tube', options, ariaLabel: '原料类别', ...props },
  })
  await flushPromises()
  return wrapper
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.replaceChildren()
})

describe('MaterialCatalogSelect', () => {
  it('提供可访问的组合框及真实选项，不渲染原生下拉', async () => {
    const view = await render()
    expect(view.find('select').exists()).toBe(false)
    expect(view.get('[role="combobox"]').attributes('aria-label')).toBe('原料类别')
    await view.get('.el-select__wrapper').trigger('click')
    await flushPromises()
    expect(document.querySelector('[role="option"][data-value="tube"]')?.getAttribute('aria-selected')).toBe('true')
    expect(document.querySelector('[data-value="tube"] .material-catalog-select-check')).not.toBeNull()
    expect(document.querySelector('[data-value="disabled"]')?.textContent).toContain('不可选')
  })

  it('方向键跳过禁用项但不改值，Enter 才确认并关闭', async () => {
    const view = await render()
    const input = view.get('[role="combobox"]')
    await input.trigger('keydown', { key: 'ArrowDown', code: 'ArrowDown' })
    await flushPromises()
    await input.trigger('keydown', { key: 'ArrowDown', code: 'ArrowDown' })
    await flushPromises()
    expect(view.emitted('update:modelValue')).toBeUndefined()
    const activeId = input.attributes('aria-activedescendant') || ''
    expect(document.getElementById(activeId)?.getAttribute('data-value')).toBe('fabric')
    await input.trigger('keydown', { key: 'Enter', code: 'Enter' })
    await flushPromises()
    expect(view.emitted('update:modelValue')).toEqual([['fabric']])
    expect(view.emitted('change')).toEqual([['fabric']])
    expect(input.attributes('aria-expanded')).toBe('false')
  })

  it('Esc 关闭活动列表，不提交待选项', async () => {
    const view = await render()
    const input = view.get('[role="combobox"]')
    await view.get('.el-select__wrapper').trigger('click')
    await input.trigger('keydown', { key: 'ArrowDown', code: 'ArrowDown' })
    await input.trigger('keydown', { key: 'Escape', code: 'Escape' })
    await flushPromises()
    expect(input.attributes('aria-expanded')).toBe('false')
    expect(view.emitted('change')).toBeUndefined()
  })

  it('Tab 不拦截焦点离开，失焦关闭且不提交', async () => {
    const view = await render()
    const input = view.get<HTMLInputElement>('[role="combobox"]')
    input.element.focus()
    await view.get('.el-select__wrapper').trigger('click')
    const event = new KeyboardEvent('keydown', { key: 'Tab', code: 'Tab', bubbles: true, cancelable: true })
    input.element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
    const next = document.createElement('button')
    document.body.append(next)
    next.focus()
    await flushPromises()
    expect(input.attributes('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(next)
    expect(view.emitted('change')).toBeUndefined()
  })

  it('禁用时跳过 Tab，点击不能展开或修改', async () => {
    const view = await render({ disabled: true })
    const input = view.get<HTMLInputElement>('[role="combobox"]')
    expect(input.element.disabled).toBe(true)
    expect(input.attributes('tabindex')).toBe('-1')
    await view.get('.el-select__wrapper').trigger('click')
    expect(input.attributes('aria-expanded')).toBe('false')
    expect(view.emitted('update:modelValue')).toBeUndefined()
  })

  it('点击选项同步 v-model 和 change，外部更新可显示新值', async () => {
    const view = await render()
    await view.get('.el-select__wrapper').trigger('click')
    await flushPromises()
    const option = document.querySelector<HTMLElement>('[role="option"][data-value="fabric"]')
    option?.click()
    await flushPromises()
    expect(view.emitted('update:modelValue')).toEqual([['fabric']])
    expect(view.emitted('change')).toEqual([['fabric']])
    await view.setProps({ modelValue: 'fabric' })
    expect(view.get('.el-select__placeholder').text()).toBe('面料')
  })

  it('暴露 focus 并将错误状态提供给实际组合框', async () => {
    const view = await render({ invalid: true })
    ;(view.vm as unknown as { focus: () => void }).focus()
    await flushPromises()
    const input = view.get('[role="combobox"]')
    expect(document.activeElement).toBe(input.element)
    expect(input.attributes('aria-invalid')).toBe('true')
    await view.setProps({ invalid: false })
    expect(input.attributes('aria-invalid')).toBe('false')
  })
})
