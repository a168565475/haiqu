import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import ProductionTaskListView from './ProductionTaskListView.vue'

const state = vi.hoisted(() => ({ canViewCost: true, panelLoads: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({
  hasPermission: (code: string) => code === 'production_tasks.view_productiontaskcost' && state.canViewCost,
  moduleCan: () => false,
}) }))
vi.mock('@/api/productionTasks', async original => ({
  ...await original<typeof import('@/api/productionTasks')>(),
  fetchProductionTasks: vi.fn(), fetchProductionTaskFilterOptions: vi.fn(),
}))
vi.mock('./ProductionTaskCostPanel.vue', async () => {
  const { defineComponent, watch } = await import('vue')
  return { default: defineComponent({
    name: 'ProductionTaskCostPanel', props: { taskId: { type: String, required: true } }, emits: ['busy-change'],
    setup(props) { watch(() => props.taskId, id => state.panelLoads(id), { immediate: true }) },
    template: '<div data-test="cost-panel" :data-task-id="taskId"><button data-test="busy" @click="$emit(\'busy-change\', true)">开始保存</button><button data-test="idle" @click="$emit(\'busy-change\', false)">保存结束</button></div>',
  }) }
})
vi.mock('@/components/common/AppWindowDialog.vue', async () => {
  const { defineComponent } = await import('vue')
  return { default: defineComponent({
    name: 'AppWindowDialog',
    props: {
      modelValue: Boolean, title: String, showClose: { type: Boolean, default: true },
      closeOnPressEscape: Boolean, closeOnClickModal: Boolean, destroyOnClose: Boolean,
      minimizable: Boolean, beforeClose: Function,
    },
    emits: ['update:modelValue', 'closed'],
    methods: {
      close() {
        const done = () => { this.$emit('update:modelValue', false); this.$emit('closed') }
        if (this.beforeClose) this.beforeClose(done)
        else done()
      },
    },
    template: '<section v-if="modelValue" :aria-label="title"><button v-if="showClose !== false" data-test="close-window" @click="close">关闭</button><slot/><slot name="footer"/></section>',
  }) }
})

const rows = ['one', 'two'].map((id, index) => ({
  id, task_number: `SC-${index + 1}`, status: 'READY', status_display: '已接单',
  products: [], followers: [], salesperson: { display_name: '业务员' },
}))
const options = { employees: [], salespeople: [], products: [], customers: [], order_sources: [], delivery_methods: [], statuses: [] }
let wrapper: ReturnType<typeof mount> | undefined
let host: HTMLDivElement | undefined
async function render() {
  host = document.createElement('div')
  document.body.appendChild(host)
  wrapper = mount(ProductionTaskListView, { attachTo: host, global: {
    plugins: [ElementPlus], stubs: { ProductionTaskScheduleDialog: true },
  } })
  await flushPromises()
  return wrapper
}

async function openRowMenu(view: ReturnType<typeof mount>, index: number) {
  const trigger = view.get(`[aria-label="打开生产任务 SC-${index + 1} 操作菜单"]`)
  await trigger.trigger('click')
  await flushPromises()
  // Element Plus 将真实菜单传送到 body，按触发器关联 ID 查找当前行。
  let menu: HTMLElement | null = null
  await vi.waitFor(() => {
    menu = document.getElementById(trigger.attributes('aria-controls') || '')
    expect(menu).not.toBeNull()
    expect(menu!.textContent).toContain('查看')
  })
  return menu!
}

async function openCost(view: ReturnType<typeof mount>, index: number) {
  const menu = await openRowMenu(view, index)
  const item = menu.querySelector<HTMLElement>('[data-test="open-cost"]')
  expect(item).not.toBeNull()
  item!.click()
  await flushPromises()
}

describe('生产任务列表成本入口', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.canViewCost = true
    vi.mocked(api.fetchProductionTasks).mockResolvedValue({ data: rows, meta: { total: 2, total_pages: 1 } } as never)
    vi.mocked(api.fetchProductionTaskFilterOptions).mockResolvedValue(options)
  })
  afterEach(() => { wrapper?.unmount(); wrapper = undefined; host?.remove(); host = undefined })

  it('真实表格通过每行操作菜单进入成本，点击后才挂载对应订单面板', async () => {
    const view = await render()
    expect(view.findAll('[data-test="open-cost"]')).toHaveLength(0)
    expect(view.findAll('.row-action-trigger')).toHaveLength(2)
    expect(view.find('[data-test="cost-panel"]').exists()).toBe(false)
    expect(state.panelLoads).not.toHaveBeenCalled()
    await openCost(view, 0)
    await flushPromises()
    expect(view.find('[aria-label="订单成本 · SC-1"]').exists()).toBe(true)
    expect(view.get('[data-test="cost-panel"]').attributes('data-task-id')).toBe('one')
    expect(state.panelLoads).toHaveBeenCalledExactlyOnceWith('one')
  })

  it('关闭销毁面板，再开同订单重新加载，其他行绑定各自订单', async () => {
    const view = await render()
    await openCost(view, 0)
    await view.get('[aria-label="订单成本 · SC-1"] [data-test="close-window"]').trigger('click')
    await flushPromises()
    expect(view.find('[data-test="cost-panel"]').exists()).toBe(false)
    await openCost(view, 0)
    expect(state.panelLoads.mock.calls.map(([id]) => id)).toEqual(['one', 'one'])
    await view.get('[aria-label="订单成本 · SC-1"] [data-test="close-window"]').trigger('click')
    await openCost(view, 1)
    expect(view.find('[aria-label="订单成本 · SC-2"]').exists()).toBe(true)
    expect(view.get('[data-test="cost-panel"]').attributes('data-task-id')).toBe('two')
    expect(state.panelLoads.mock.calls.map(([id]) => id)).toEqual(['one', 'one', 'two'])
  })

  it('保存忙碌时禁用外层关闭和 Escape，窗口不允许遮罩关闭或最小化', async () => {
    const view = await render()
    await openCost(view, 0)
    const dialog = () => view.findAllComponents({ name: 'AppWindowDialog' }).find(item => item.props('title') === '订单成本 · SC-1')!
    expect(dialog().props()).toMatchObject({ closeOnClickModal: false, destroyOnClose: true, minimizable: false })
    await view.get('[data-test="busy"]').trigger('click')
    expect(dialog().props()).toMatchObject({ showClose: false, closeOnPressEscape: false })
    expect(view.find('[aria-label="订单成本 · SC-1"] [data-test="close-window"]').exists()).toBe(false)
    await view.get('[data-test="idle"]').trigger('click')
    expect(dialog().props()).toMatchObject({ showClose: true, closeOnPressEscape: true })
  })

  it('无成本查看权限不提供入口，也不挂载会加载成本的面板', async () => {
    state.canViewCost = false
    const view = await render()
    const menu = await openRowMenu(view, 0)
    expect(menu.querySelector('[data-test="open-cost"]')).toBeNull()
    expect(view.findAll('[data-test="open-cost"]')).toHaveLength(0)
    expect(view.find('[data-test="cost-panel"]').exists()).toBe(false)
    expect(state.panelLoads).not.toHaveBeenCalled()
  })
})
