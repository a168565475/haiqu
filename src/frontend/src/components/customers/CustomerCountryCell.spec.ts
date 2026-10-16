import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CustomerCountryCell from './CustomerCountryCell.vue'

describe('客户国家单元格', () => {
  it('使用两位国家代码的小写图片地址，同时保留完整国家名', () => {
    const wrapper = mount(CustomerCountryCell, { props: { countryCode: 'cN', countryName: '中国' } })

    expect(wrapper.get('img').attributes('src')).toBe('https://flagcdn.com/24x18/cn.png')
    expect(wrapper.text()).toBe('中国')
    expect(wrapper.attributes('title')).toBe('中国')
  })

  it.each(['', 'USA', 'C1'])('代码 %s 无效时仅显示国家名称', countryCode => {
    const wrapper = mount(CustomerCountryCell, { props: { countryCode, countryName: '未知国家' } })

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toBe('未知国家')
    expect(wrapper.attributes('title')).toBe('未知国家')
  })

  it('国旗加载失败后隐藏图片，国家名称仍可见', async () => {
    const wrapper = mount(CustomerCountryCell, { props: { countryCode: 'DE', countryName: '德国' } })
    await wrapper.get('img').trigger('error')

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toBe('德国')
    expect(wrapper.attributes('title')).toBe('德国')
  })

  it('失败后切换国家时重新加载新国旗并更新名称', async () => {
    const wrapper = mount(CustomerCountryCell, { props: { countryCode: 'DE', countryName: '德国' } })
    await wrapper.get('img').trigger('error')
    await wrapper.setProps({ countryCode: 'JP', countryName: '日本' })

    expect(wrapper.get('img').attributes('src')).toBe('https://flagcdn.com/24x18/jp.png')
    expect(wrapper.text()).toBe('日本')
    expect(wrapper.attributes('title')).toBe('日本')
  })
})
