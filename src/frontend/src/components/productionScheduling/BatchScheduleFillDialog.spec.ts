import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import BatchScheduleFillDialog from './BatchScheduleFillDialog.vue'

let wrapper: ReturnType<typeof mount> | undefined

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.innerHTML = ''
})

describe('BatchScheduleFillDialog', () => {
  it('将窗口关闭请求同步给父级 v-model', async () => {
    wrapper = mount(BatchScheduleFillDialog, {
      props: { modelValue: true, crafts: [], selectedCount: 1 },
      global: { plugins: [ElementPlus] },
    })

    wrapper.findComponent(AppWindowDialog).vm.$emit('update:modelValue', false)
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })
})
