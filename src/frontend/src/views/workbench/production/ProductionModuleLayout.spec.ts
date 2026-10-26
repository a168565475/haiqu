import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import ProductionModuleLayout from './ProductionModuleLayout.vue'
import type { OverviewModuleKey } from './useModuleFocus'

const modules: { key: OverviewModuleKey; title: string; subtitle?: string; summary: string }[] = [
  { key: 'production', title: '生产任务', subtitle: '当前筛选范围', summary: '2 单任务' },
  { key: 'delivery', title: '近期交期', summary: '1 单临期' },
  { key: 'outsourcing', title: '委外待回货', summary: '3 单待回' },
  { key: 'todo', title: '协调重点', summary: '2 项关注' },
]
const wrappers: ReturnType<typeof mount>[] = []

function renderPage(variant: 'owner' | 'workshop' = 'owner') {
  const pageModules = variant === 'owner' ? modules : [modules[0]!, { key: 'output' as const, title: '当日报工', summary: '5 笔报工' }, modules[3]!]
  const wrapper = mount(ProductionModuleLayout, {
    attachTo: document.body,
    props: { modules: pageModules, variant },
    slots: Object.fromEntries(pageModules.map(module => [module.key, ({ expanded }: { expanded: boolean }) => h('div', { 'data-slot': module.key, 'data-expanded': expanded }, [
      h('a', { href: `/tasks/${module.key}` }, '查看任务'), h('input', { 'aria-label': `${module.title}备注` }),
    ])])),
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  document.body.innerHTML = ''
})

describe('工作台模块容器', () => {
  it('概览展开按钮独立于业务链接，展开及切换保留卡片和槽内容 DOM', async () => {
    const wrapper = renderPage()
    const cards = wrapper.findAll('.pml-module').map(card => card.element)
    const contents = wrapper.findAll('[data-slot]').map(content => content.element)
    const production = wrapper.find('[data-module="production"]')
    await production.find('input').setValue('保留输入')
    expect(production.find('.pml-mini-open').exists()).toBe(false)
    expect(production.find('a').attributes('href')).toBe('/tasks/production')
    production.find('a').element.addEventListener('click', event => event.preventDefault())
    await production.find('a').trigger('click')
    await production.find('input').trigger('click')
    expect(wrapper.attributes('data-active-module')).toBe('overview')

    await production.find('h2').trigger('click')
    await nextTick()
    expect(wrapper.attributes('data-active-module')).toBe('production')
    expect(wrapper.findAll('.is-mini')).toHaveLength(3)
    expect(production.find('[data-slot]').attributes('data-expanded')).toBe('true')
    expect(wrapper.find('[data-module="outsourcing"] .pml-body').attributes('hidden')).toBeDefined()

    await wrapper.find('[data-module="outsourcing"] [data-module-open]').trigger('click')
    await nextTick()
    expect(wrapper.attributes('data-active-module')).toBe('outsourcing')
    expect(wrapper.find('[data-module="outsourcing"] [data-slot]').attributes('data-expanded')).toBe('true')
    expect(production.find('[data-slot]').attributes('data-expanded')).toBe('false')
    expect(wrapper.findAll('.pml-module').map(card => card.element)).toEqual(cards)
    expect(wrapper.findAll('[data-slot]').map(content => content.element)).toEqual(contents)
    expect((production.find('input').element as HTMLInputElement).value).toBe('保留输入')

    await wrapper.find('[data-module-close]').trigger('click')
    await nextTick()
    expect(wrapper.attributes('data-active-module')).toBe('overview')
    expect(wrapper.findAll('.is-mini')).toHaveLength(0)
    expect(wrapper.findAll('.pml-body[hidden]')).toHaveLength(0)
    expect(document.activeElement).toBe(wrapper.find('[data-module="outsourcing"] [data-module-open]').element)
  })

  it('车间使用两个缩略模块，Escape 返回概览', async () => {
    const wrapper = renderPage('workshop')
    await wrapper.find('[data-module="output"] [data-module-open]').trigger('click')
    await nextTick()
    expect(wrapper.findAll('.is-mini')).toHaveLength(2)
    expect(wrapper.find('.pml-caption').text()).toContain('当日报工')
    await wrapper.trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(wrapper.attributes('data-active-module')).toBe('overview')
    expect(wrapper.find('.pml-dock').exists()).toBe(false)
  })

  it('外部入口可打开已有模块，未提供的模块不会进入空详情', async () => {
    const wrapper = mount(defineComponent({
      components: { ProductionModuleLayout },
      setup: () => ({ modules }),
      template: '<ProductionModuleLayout ref="layout" :modules="modules" variant="owner" />',
    }))
    wrappers.push(wrapper)
    const layout = wrapper.vm.$refs.layout as { openModule: (key: OverviewModuleKey) => Promise<void> | undefined }
    await layout.openModule('outsourcing')
    expect(wrapper.find('[data-testid="production-module-layout"]').attributes('data-active-module')).toBe('outsourcing')
    await layout.openModule('output')
    expect(wrapper.find('[data-testid="production-module-layout"]').attributes('data-active-module')).toBe('outsourcing')
  })
})
