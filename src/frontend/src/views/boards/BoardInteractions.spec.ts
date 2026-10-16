import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Component } from 'vue'

const modules = import.meta.glob<{ default: Component }>('./components/*.vue')
const orders = [
  { id: 'DEMO-001', productCode: 'DEMO-CHAIR', product: '折叠椅', specification: '绿色', planned: 100, priority: '正常', processes: [{ label: '裁剪', completed: 100, total: 100 }, { label: '缝制', completed: 25, total: 100 }] },
  { id: 'DEMO-002', productCode: 'DEMO-TABLE', product: '露营桌', specification: '原木色', planned: 80, priority: '紧急', processes: [{ label: '组装', completed: 0, total: 80 }] },
]

async function load(name: string) {
  const loader = modules[`./components/${name}.vue`]
  expect(loader, `${name} 尚未实现`).toBeTypeOf('function')
  return (await loader!()).default
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('看板演示交互', () => {
  it('人员组件只显示传入记录，不自行混入模拟员工，方便以后切换真实数据', async () => {
    const component = await load('BoardEmployeeList')
    const wrapper = mount(component, { props: { rows: [{ name: '传入员工', reported: 5, defective: 0 }] } })
    expect(wrapper.findAll('article')).toHaveLength(1)
    await wrapper.setProps({ rows: [] })
    expect(wrapper.findAll('article')).toHaveLength(0)
    expect(wrapper.text()).toContain('暂无演示记录')
    wrapper.unmount()
  })

  it('搜索只筛选内存数据，支持编号/产品/规格并展示真实空结果', async () => {
    const component = await load('BoardProcessTable')
    const wrapper = mount(component, { props: { rows: orders, searchable: true } })
    const input = wrapper.get('input')
    await input.setValue('demo-chair')
    expect(wrapper.text()).toContain('折叠椅')
    expect(wrapper.text()).not.toContain('露营桌')
    await input.setValue('原木色')
    expect(wrapper.text()).toContain('露营桌')
    await input.setValue('不存在的工单')
    expect(wrapper.text()).toContain('暂无匹配工单')
    await input.setValue('')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(orders).toHaveLength(2)
    wrapper.unmount()
  })

  it('工序节点有完成、进行中、未开始的文字说明', async () => {
    const component = await load('BoardProcessTable')
    const wrapper = mount(component, { props: { rows: orders } })
    const labels = wrapper.findAll('[aria-label]').map(node => node.attributes('aria-label')).join(' ')
    expect(labels).toContain('裁剪：已完成，100/100')
    expect(labels).toContain('缝制：进行中，25/100')
    expect(labels).toContain('组装：未开始，0/80')
    wrapper.unmount()
  })

  it('报工每秒收起首行并轮换，焦点暂停，原数据不重排', async () => {
    let frame: FrameRequestCallback | undefined
    const cancel = vi.fn()
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frame = callback; return 1 })
    vi.stubGlobal('cancelAnimationFrame', cancel)
    const rows = [{ worker: '员工A' }, { worker: '员工B' }]
    const component = await load('BoardFeedTable')
    const wrapper = mount(component, { props: { columns: [{ key: 'worker', label: '员工' }], rows } })
    const advance = async (from: number, to: number) => {
      for (let time = from; time <= to; time += 20) frame?.(time)
      await wrapper.vm.$nextTick()
    }
    await advance(0, 500)
    expect(Number(wrapper.get('[data-feed-row]').element.getAttribute('style')?.match(/opacity: ([\d.]+)/)?.[1])).toBeCloseTo(0.5)
    await wrapper.get('[data-motion="feed"]').trigger('focusin')
    await advance(520, 1000)
    expect(wrapper.findAll('tbody tr')[0]!.text()).toBe('员工A')
    await wrapper.get('[data-motion="feed"]').trigger('focusout')
    await advance(1020, 1500)
    expect(wrapper.findAll('tbody tr')[0]!.text()).toBe('员工B')
    expect(rows[0]!.worker).toBe('员工A')
    wrapper.unmount()
    expect(cancel).toHaveBeenCalled()
  })

  it('离开独立大屏后释放时钟和监听，恢复原页面标题', async () => {
    vi.useFakeTimers()
    const originalTitle = document.title
    const component = await load('BoardShell')
    const wrapper = mount(component, { props: { title: '产线大屏' }, global: { stubs: { RouterLink: true } } })
    expect(document.title).toBe('产线大屏 · 演示看板')
    expect(vi.getTimerCount()).toBeGreaterThan(0)
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
    expect(document.title).toBe(originalTitle)
  })
})
