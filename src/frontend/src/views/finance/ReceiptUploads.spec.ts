import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReceiptUploads from './ReceiptUploads.vue'
import { discardReceiptUpload } from '@/api/financeReceipts'
import type { ReceiptUpload } from '@/types/financeReceipts'

vi.mock('@/api/financeReceipts', () => ({ discardReceiptUpload: vi.fn(), uploadReceiptFile: vi.fn(), fetchReceiptUploadContent: vi.fn() }))
const upload = (id: string) => ({ id, status: 'UNBOUND', original_name: id + '.png', scan_status: 'SKIPPED', scan_label: '未扫描（当前配置跳过）' } as ReceiptUpload)
describe('水单正式清理（隔离组件测试）', () => {
  beforeEach(() => vi.clearAllMocks())
  it('正常水单只展示文件名，异常扫描和待清理状态仍然可见', async () => {
    const wrapper = mount(ReceiptUploads, { props: { modelValue: [upload('a')], statementId: 'statement' }, global: { plugins: [ElementPlus], stubs: { AppWindowDialog: true } } })
    try {
      expect(wrapper.text()).toContain('a.png')
      expect(wrapper.text()).not.toContain('未扫描（当前配置跳过）')
      expect(wrapper.text()).not.toContain('尚未绑定收款')
      await wrapper.setProps({ modelValue: [{ ...upload('a'), status: 'DISCARD_PENDING', scan_status: 'FAILED', scan_label: '扫描失败' }] })
      expect(wrapper.text()).toContain('清理失败，待重试')
      expect(wrapper.text()).toContain('扫描失败')
      expect(wrapper.findAll('[role="alert"]')).toHaveLength(2)
    } finally { wrapper.unmount() }
  })
  it('逐条清理不会因旧props恢复已删除水单', async () => {
    vi.mocked(discardReceiptUpload).mockImplementation(async id => ({ ...upload(id), status: 'DISCARDED' }))
    const wrapper = mount(ReceiptUploads, { props: { modelValue: [upload('a'), upload('b')], statementId: 'statement' }, global: { plugins: [ElementPlus], stubs: { AppWindowDialog: true } } })
    try {
      expect(await wrapper.vm.discardAll()).toBe(true); await flushPromises()
      expect(wrapper.emitted('update:modelValue')).toEqual([[[upload('b')]], [[]]])
      expect(discardReceiptUpload).toHaveBeenCalledTimes(2)
    } finally { wrapper.unmount() }
  })
  it('清理失败保留失败项并阻止父层离开', async () => {
    vi.mocked(discardReceiptUpload).mockRejectedValue(new Error('disk failed'))
    const wrapper = mount(ReceiptUploads, { props: { modelValue: [upload('a')], statementId: 'statement' }, global: { plugins: [ElementPlus], stubs: { AppWindowDialog: true } } })
    try { expect(await wrapper.vm.discardAll()).toBe(false); expect(wrapper.emitted('update:modelValue')).toBeUndefined() }
    finally { wrapper.unmount() }
  })
})
