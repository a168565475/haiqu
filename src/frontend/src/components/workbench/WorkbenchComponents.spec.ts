import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WorkbenchMetricCard from './WorkbenchMetricCard.vue'
import WorkbenchSection from './WorkbenchSection.vue'
import SalesWorkbench from '@/views/workbench/SalesWorkbench.vue'

describe('工作台公共组件', () => {
  it('业务员工作台可显示真实接口返回的无截止时间任务', () => {
    const wrapper = mount(SalesWorkbench, {
      props: {
        metrics: [], risks: [], taskState: 'READY', riskState: 'EMPTY', loadingMetrics: false,
        canAddCommunication: false, canAddInquiry: false,
        tasks: [{
          id: 'no-deadline', title: '无截止时间任务', status: 'PENDING', status_display: '待处理',
          priority: 'NORMAL', priority_display: '普通', due_at: null, completed_at: null,
          assignee: null, source: null, created_at: '2026-10-16T08:00:00+08:00', updated_at: '2026-10-16T08:00:00+08:00',
        }],
      },
    })
    expect(wrapper.get('tbody tr').text()).toContain('无截止时间任务')
    expect(wrapper.get('tbody tr').text()).toContain('未设置')
    expect(wrapper.find('.is-overdue').exists()).toBe(false)
    expect(wrapper.get('.task-tabs').text().replace(/\s/g, '')).toContain('逾期0今天0')
    wrapper.unmount()
  })

  it('只给演示口径显示演示数据标记', () => {
    const demo = mount(WorkbenchMetricCard, {
      props: { item: { key: 'demo', label: '演示指标', value: '8', note: '无接口口径', tone: 'neutral', origin: 'DEMO' } },
    })
    const live = mount(WorkbenchMetricCard, {
      props: { item: { key: 'today', label: '真实指标', value: '3', note: '来自任务中心', tone: 'neutral', origin: 'LIVE' } },
    })
    expect(demo.text()).toContain('演示数据')
    expect(live.text()).not.toContain('演示数据')
  })

  it('错误状态不渲染正文，并提供重新加载操作', async () => {
    const wrapper = mount(WorkbenchSection, {
      props: { title: '任务', state: 'ERROR', errorMessage: '任务接口异常' },
      slots: { default: '<div data-content>不应出现</div>' },
    })
    expect(wrapper.text()).toContain('任务接口异常')
    expect(wrapper.find('[data-content]').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('空数据状态显示明确占位', () => {
    const wrapper = mount(WorkbenchSection, { props: { title: '风险客户', state: 'EMPTY' } })
    expect(wrapper.text()).toContain('暂无数据')
  })
})
