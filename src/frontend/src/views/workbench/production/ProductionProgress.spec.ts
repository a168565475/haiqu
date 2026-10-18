import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProductionProgress from './ProductionProgress.vue'

describe('生产阶段进度显示', () => {
  it.each([
    ['NOT_CONFIGURED', '待配置工价'],
    ['NOT_APPLICABLE', '不适用'],
    ['FORBIDDEN', '无查看权限'],
  ])('保留 %s 的原因，不把未知进度画成 0%%', (status, display) => {
    const wrapper = mount(ProductionProgress, { props: { label: '金工汇总', status, display, percentage: null } })
    expect(wrapper.text()).toContain(display)
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('0%')
  })

  it('真实零保持可访问的零进度，超过100%的绘制限制在轨道内', async () => {
    const wrapper = mount(ProductionProgress, { props: { label: '成品入库', status: 'READY', display: '0%', percentage: 0 } })
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('0')
    expect(wrapper.text()).toContain('0%')
    await wrapper.setProps({ percentage: 125, display: '125%' })
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('100')
    expect(wrapper.get('.pd-progress__fill').attributes('style')).toContain('width: 100%')
    expect(wrapper.text()).toContain('125%')
  })

  it('无有效百分比时保留未知状态', () => {
    const wrapper = mount(ProductionProgress, { props: { label: '裁缝汇总', status: 'READY', display: '', percentage: Number.NaN } })
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('—')
  })
})
