import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchPublishedOptions } from '@/api/referenceData'
import { useOptions } from './useOptions'
import type { PublishedOptionsResponse } from '@/types/referenceData'
vi.mock('@/api/referenceData', () => ({ fetchPublishedOptions: vi.fn() }))
function response(label: string): PublishedOptionsResponse {
  return { data: [{ id: 'item', code: 'ITEM', label, english_label: '', status: 'ACTIVE', sort_order: 1, color: '', extra: {} }], meta: { config_version: 1 } }
}
function render() {
  return mount(defineComponent({ setup() {
    const options = useOptions('CUSTOMER_GRADE', 'historical-id'); void options.load()
    return { choices: options.options, reload: options.reload }
  }, template: '<div><span v-for="item in choices" :key="item.id">{{ item.label }}</span><button @click="reload">刷新</button></div>' }))
}
describe('页面按需配置', () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.mocked(fetchPublishedOptions).mockReset().mockResolvedValueOnce(response('原值')).mockResolvedValue(response('新值')) })
  it('已打开页面保持显示，再次进入使用最新值', async () => {
    const first = render(); await flushPromises(); expect(first.text()).toContain('原值')
    const second = render(); await flushPromises(); expect(second.text()).toContain('新值')
    expect(first.text()).toContain('原值'); first.unmount(); second.unmount()
  })
  it('主动重新使用时读取新值并保留历史项参数', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('新值')
    expect(fetchPublishedOptions).toHaveBeenLastCalledWith('CUSTOMER_GRADE', 'historical-id'); wrapper.unmount()
  })
})
