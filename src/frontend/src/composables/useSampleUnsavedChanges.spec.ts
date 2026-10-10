import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useSampleUnsavedChanges } from './useSampleUnsavedChanges'

const FormPage = defineComponent({
  setup() {
    const note = ref('')
    useSampleUnsavedChanges(() => Boolean(note.value))
    return { note }
  },
  template: '<input v-model="note" aria-label="未保存内容">',
})
const Host = defineComponent({
  components: { RouterView },
  // 与 App.vue 一样，完整地址变化会重新挂载页面。
  template: '<RouterView v-slot="{ Component, route }"><component :is="Component" :key="route.fullPath" /></RouterView>',
})
const wrappers: ReturnType<typeof mount>[] = []

async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/samples/:sampleId/edit', component: FormPage },
    { path: '/samples', component: { template: '<p>列表</p>' } },
  ] })
  await router.push('/samples/first/edit')
  await router.isReady()
  const wrapper = mount(Host, { global: { plugins: [router] } })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}

afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('打样页未保存内容与真实路由', () => {
  it.each(['/samples/first/edit?sourceId=changed', '/samples/second/edit', '/samples'])('取消切换 %s 时保留原地址及输入', async target => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    const { wrapper, router } = await render()
    await wrapper.find('input').setValue('不要丢失')
    await router.push(target)
    await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.fullPath).toBe('/samples/first/edit')
    expect(wrapper.find('input').element.value).toBe('不要丢失')
  })

  it('确认切换申请后加载新页面，不保留上一份申请输入', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
    const { wrapper, router } = await render()
    await wrapper.find('input').setValue('旧申请意见')
    await router.push('/samples/second/edit')
    await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.fullPath).toBe('/samples/second/edit')
    expect(wrapper.find('input').element.value).toBe('')
  })

  it('没有修改时直接切换，浏览器关闭保护只在存在输入时生效', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
    const { wrapper, router } = await render()
    await router.push('/samples/first/edit?sourceId=changed')
    await flushPromises()
    expect(confirm).not.toHaveBeenCalled()
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false)
    await wrapper.find('input').setValue('未保存')
    const dirty = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirty)
    expect(dirty.defaultPrevented).toBe(true)
    wrapper.unmount()
    wrappers.splice(wrappers.indexOf(wrapper), 1)
    const unmounted = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unmounted)
    expect(unmounted.defaultPrevented).toBe(false)
  })
})
