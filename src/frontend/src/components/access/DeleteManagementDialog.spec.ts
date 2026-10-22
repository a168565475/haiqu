import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DeleteManagementDialog from './DeleteManagementDialog.vue'
import * as api from '@/api/access'

vi.mock('@/api/access', () => ({ previewDeletion: vi.fn(), deleteSelected: vi.fn(), accessError: (e: Error) => e.message }))
vi.mock('element-plus', () => ({ ElMessage: { success: vi.fn() } }))
const items = [{ id: 'employee-1', etag: '"version1"' }]
const preview = { rows: [{ id: 'employee-1', name: '待删除员工', account: 'example', mode: 'ARCHIVE', reason: '保留历史记录' }], token: 'preview-token', etag: '"preview-version"' }
function render(kind = 'employees') {
  return mount(DeleteManagementDialog, { props: { kind: kind as 'employees', items }, global: { stubs: {
    AppWindowDialog: { template: '<div><slot/><slot name="footer"/></div>' },
  } } })
}
function confirm(wrapper: ReturnType<typeof render>) { return wrapper.findAll('button').find(button => button.text() === '确认删除')! }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.previewDeletion).mockResolvedValue(preview as never) })
describe('管理删除确认', () => {
  it('先展示影响，只有确认后提交，并处理删除当前用户的返回值', async () => {
    vi.mocked(api.deleteSelected).mockResolvedValue({ rows: preview.rows, self_deleted: true } as never)
    const wrapper = render(); await flushPromises()
    expect(wrapper.text()).toContain('保留历史记录')
    expect(api.deleteSelected).not.toHaveBeenCalled()
    await confirm(wrapper).trigger('click'); await flushPromises()
    expect(api.deleteSelected).toHaveBeenCalledWith('employees', items, preview)
    expect(wrapper.emitted('deleted')).toEqual([[true]])
    wrapper.unmount()
  })
  it('预览失败禁止确认', async () => {
    vi.mocked(api.previewDeletion).mockRejectedValue(new Error('没有权限'))
    const wrapper = render(); await flushPromises()
    expect(wrapper.text()).toContain('没有权限')
    expect(confirm(wrapper).attributes('disabled')).toBeDefined()
    expect(api.deleteSelected).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('并发冲突后丢弃旧预览，不能重复提交', async () => {
    vi.mocked(api.deleteSelected).mockRejectedValue(new Error('记录已变化'))
    const wrapper = render(); await flushPromises()
    await confirm(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('记录已变化')
    expect(confirm(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.emitted('deleted')).toBeUndefined(); wrapper.unmount()
  })
  it('角色预览不显示员工账号退出提示，取消不写入', async () => {
    const wrapper = render('roles'); await flushPromises()
    expect(wrapper.text()).not.toContain('退出登录')
    await wrapper.findAll('button').find(button => button.text() === '取消')!.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(api.deleteSelected).not.toHaveBeenCalled(); wrapper.unmount()
  })
})
