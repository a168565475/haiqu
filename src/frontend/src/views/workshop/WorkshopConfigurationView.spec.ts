import { shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routerState = vi.hoisted(() => ({
  route: { query: {} as Record<string, string> },
  push: vi.fn(),
  replace: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routerState.route,
  useRouter: () => ({ push: routerState.push, replace: routerState.replace }),
}))

import WorkshopConfigurationView from './WorkshopConfigurationView.vue'

describe('生产车间配置入口', () => {
  beforeEach(() => {
    routerState.route.query = {}
    routerState.push.mockReset()
    routerState.replace.mockReset()
  })

  it('提供三个入口并把当前全屏入口写入查询参数', async () => {
    const wrapper = shallowMount(WorkshopConfigurationView, {
      global: { stubs: { ElAlert: true, ElTag: true, ElDialog: true, WorkshopConfigManager: true } },
    })
    expect(wrapper.get('h1').text()).toBe('生产配置')
    const cards = wrapper.findAll('.entry-card')
    expect(cards).toHaveLength(3)
    expect(cards[0]?.text()).toContain('直接为生产部员工安排车间、岗位与主管')
    expect(cards[0]?.text()).toContain('员工来源：行政生产部')
    expect(cards[0]?.text()).not.toContain('81 人')
    await cards[0]?.trigger('click')
    await cards[1]?.trigger('click')
    await cards[2]?.trigger('click')
    expect(routerState.push).toHaveBeenNthCalledWith(1, { query: { panel: 'employees' } })
    expect(routerState.push).toHaveBeenNthCalledWith(2, { query: { panel: 'crafts' } })
    expect(routerState.push).toHaveBeenNthCalledWith(3, { query: { panel: 'operations' } })
    expect(wrapper.text()).not.toContain('车间信息')
  })

  it('不在入口页提供 Excel 导入按钮', () => {
    const wrapper = shallowMount(WorkshopConfigurationView, {
      global: { stubs: { ElAlert: true, ElTag: true, ElDialog: true, WorkshopConfigManager: true } },
    })
    expect(wrapper.text()).not.toContain('导入 Excel')
  })
})
