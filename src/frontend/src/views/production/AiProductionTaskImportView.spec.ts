import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import ElementPlus, { ElFormItem, ElMessage, ElMessageBox, ElOption, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import AiProductionTaskImportView from './AiProductionTaskImportView.vue'

const api = vi.hoisted(() => ({ config: vi.fn(), save: vi.fn(), clear: vi.fn(), upload: vi.fn(), fetch: vi.fn(), list: vi.fn(), review: vi.fn(), remove: vi.fn(), createTask: vi.fn(), createBoms: vi.fn(), remap: vi.fn(), match: vi.fn(), select: vi.fn(), restore: vi.fn() }))
const navigation = vi.hoisted(() => ({ query: {} as Record<string, string>, push: vi.fn(), replace: vi.fn(), leave: null as (() => Promise<boolean>) | null }))
const child = vi.hoisted(() => ({ taskPayload: vi.fn(), bomPlans: vi.fn(), applyMatches: vi.fn() }))
vi.mock('@/api/aiProductionImport', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/aiProductionImport')>(),
  fetchAiOpenAiConfig: api.config, saveAiOpenAiConfig: api.save, clearAiOpenAiConfig: api.clear,
  uploadAiProductionImport: api.upload, fetchAiProductionImport: api.fetch, listAiProductionImports: api.list,
  saveAiImportReview: api.review, deleteAiProductionImport: api.remove,
  createAiProductionTaskDraft: api.createTask, createAiProductionBoms: api.createBoms,
  remapAiProductionImport: api.remap, selectAiImportTask: api.select, restoreAiImportReview: api.restore,
  matchAiProductionMaterials: api.match,
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: navigation.push, replace: navigation.replace }), useRoute: () => navigation,
  onBeforeRouteLeave: (callback: () => Promise<boolean>) => { navigation.leave = callback } }))

let nextMountId = 0
const TaskFormStub = defineComponent({ name: 'TaskFormStub', props: ['modelValue', 'result', 'disabled'], emits: ['update:modelValue'],
  setup(props, { expose }) { expose({ buildPayload: () => child.taskPayload(props.modelValue) }); return { mountId: ++nextMountId, initialTaskNumber: props.modelValue?.task_number || props.result?.task?.task_number?.value || '' } },
  template: '<div data-testid="task-form" :data-mount-id="mountId" :data-initial-task="initialTaskNumber">{{ modelValue?.task_number || "待核对任务" }}</div>' })
const BomFormStub = defineComponent({ name: 'BomFormStub', props: ['modelValue', 'result', 'taskProducts', 'disabled', 'matchingMaterials'], emits: ['update:modelValue', 'match-materials'],
  setup(props, { expose }) { expose({ buildPlans: () => child.bomPlans(props.modelValue), applyLatestMatches: (result: unknown) => child.applyMatches(result) }); return { mountId: ++nextMountId } },
  template: '<div data-testid="bom-form" :data-mount-id="mountId">BOM 可编辑区</div>' })
const DrawerStub = defineComponent({ props: ['modelValue'], template: '<aside v-if="modelValue" data-testid="history"><slot /></aside>' })
const ConfigDialogStub = defineComponent({ props: ['modelValue', 'title', 'beforeClose', 'showClose'], emits: ['update:modelValue'],
  setup(props, { emit }) {
    const close = () => props.beforeClose?.(() => emit('update:modelValue', false))
    return { close }
  },
  template: '<section v-if="modelValue" role="dialog" :aria-label="title" data-testid="config-dialog"><button v-if="showClose" aria-label="关闭配置" @click="close">关闭</button><slot /><slot name="footer" /></section>' })
const config = { id: 'config-1', key_configured: true, label: '主 Key', provider: 'openai', model: 'gpt-6.1-sol', key_last4: '1234', key_fingerprint: 'sha256:abcd', updated_at: '2026-11-11T00:00:00Z' }
const record = (overrides: Record<string, unknown> = {}) => ({ id: 'import-1', state: 'REVIEW', phase: 'recognition', original_name: 'task.xlsx',
  result: { task: { task_number: { value: 'HT26149' } }, products: [] }, review_draft: null, issues: [], sources: [], error_code: '', updated_at: '2026-11-13T01:00:00Z', ...overrides })
const response = (overrides: Record<string, unknown> = {}, etag = '"v2"') => ({ data: record(overrides), etag })
const taskResults = {
  main: { task: { task_number: { value: 'HT26149' } }, products: [{ product_key: 'main-product' }], boms: [{ product_key: 'main-product' }] },
  second: { task_key: 'second', task: { task_number: { value: 'HT26150' } }, products: [{ product_key: 'second-product' }], boms: [{ product_key: 'second-product' }] },
}
const multiResponse = (activeTaskKey = 'main', overrides: Record<string, unknown> = {}, etag = '"v2"') => response({
  active_task_key: activeTaskKey,
  result: { ...taskResults.main, additional_tasks: [taskResults.second], recognition_meta: { version: 2 } },
  task_choices: [{ task_key: 'main', task_number: 'HT26149', state: 'REVIEW' }, { task_key: 'second', task_number: 'HT26150', state: 'REVIEW' }],
  ...overrides,
}, etag)
const wrappers: ReturnType<typeof mount>[] = []
type Wrapper = ReturnType<typeof mount>
async function render() {
  const wrapper = mount(AiProductionTaskImportView, { global: { plugins: [ElementPlus], stubs: { AiImportTaskForm: TaskFormStub, AiImportBomForm: BomFormStub, ElDrawer: DrawerStub, AppWindowDialog: ConfigDialogStub } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
function button(wrapper: Wrapper, label: string) {
  const found = wrapper.findAll('button').find(item => item.text() === label)
  expect(found, `应显示按钮：${label}`).toBeDefined(); return found!
}
function effortSelect(wrapper: Wrapper, label: string) {
  const field = wrapper.findAllComponents(ElFormItem).find(item => item.props('label') === label)
  expect(field, label).toBeDefined()
  return field!.getComponent(ElSelect)
}
function taskTab(wrapper: Wrapper, key: string) { return wrapper.get(`[role="tab"][data-task-key="${key}"]`) }
function selectedTask(wrapper: Wrapper) { return wrapper.get('[role="tab"][aria-selected="true"]').attributes('data-task-key') }
async function selectFile(wrapper: Wrapper, name = 'task.xlsx') {
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['sheet'], name)] })
  await input.trigger('change'); return input
}
async function editTask(wrapper: Wrapper, payload: Record<string, unknown>) { wrapper.findComponent(TaskFormStub).vm.$emit('update:modelValue', payload); await flushPromises() }
async function editBom(wrapper: Wrapper, plans: Array<Record<string, unknown>>) { wrapper.findComponent(BomFormStub).vm.$emit('update:modelValue', plans); await flushPromises() }
function expectNoBusinessCreation() { expect(api.createTask).not.toHaveBeenCalled(); expect(api.createBoms).not.toHaveBeenCalled() }

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); navigation.query = {}; navigation.leave = null
  navigation.replace.mockResolvedValue(undefined); navigation.push.mockResolvedValue(undefined)
  api.config.mockResolvedValue({ data: config, etag: '"c1"' }); api.upload.mockResolvedValue(response()); api.fetch.mockResolvedValue(response())
  api.save.mockResolvedValue({ data: config, etag: '"c2"' }); api.clear.mockResolvedValue(undefined)
  api.list.mockResolvedValue({ count: 1, results: [record()] })
  api.review.mockImplementation(async (_id, review) => response({ review_draft: review }, '"v3"')); api.remove.mockResolvedValue(undefined); api.remap.mockResolvedValue(response())
  api.match.mockResolvedValue(response({}, '"matched-v4"'))
  child.taskPayload.mockImplementation(async payload => payload); child.bomPlans.mockImplementation(plans => plans)
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>); vi.spyOn(ElMessage, 'success').mockReturnValue({ close: vi.fn() })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks() })

describe('AI 生产导入主流程（子表单和 API 使用测试替身）', () => {
  it.each(['saved-import', ['saved-import']])('新上传材料对应失败时读取第一阶段已保存记录，保留错误且无需重上传：%j', async savedId => {
    const wrapper = await render()
    const error = new AxiosError('Request failed', undefined, undefined, undefined, { status: 400, data: { error: { message: 'OPENAI_REQUEST_FAILED', field_errors: { record_id: savedId, detail: 'ERP材料对应超时，表格识别已保存' } } } } as never)
    api.upload.mockRejectedValueOnce(error)
    const recovered = response({ id: 'saved-import', result: { ...taskResults.main, recognition_meta: { erp_assistant: { status: 'failed' } } }, error_code: 'OPENAI_REQUEST_FAILED', issues: [{ message: '材料对应尚未完成' }] })
    api.fetch.mockResolvedValueOnce(recovered)
    await selectFile(wrapper); await button(wrapper, '开始识别').trigger('click'); await flushPromises()
    expect(api.fetch).toHaveBeenCalledWith('saved-import')
    expect(wrapper.findComponent(BomFormStub).props('result')).toEqual(recovered.data.result)
    expect(wrapper.text()).toContain('ERP材料对应超时，表格识别已保存')
    expect(wrapper.findAll('button').some(item => item.text() === '开始识别')).toBe(false)
    expect(navigation.replace).toHaveBeenCalledWith({ query: { importId: 'saved-import' } })
    expect(api.upload).toHaveBeenCalledTimes(1)
    expect(api.match).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })

  it('已保存第一阶段结果读取失败时提示从记录继续，不重复上传', async () => {
    const wrapper = await render()
    api.upload.mockRejectedValueOnce(new AxiosError('Request failed', undefined, undefined, undefined, { status: 400, data: { error: { message: 'ERP材料对应失败', field_errors: { record_id: 'saved-import' } } } } as never))
    api.fetch.mockRejectedValueOnce(new Error('读取网络失败'))
    await selectFile(wrapper); await button(wrapper, '开始识别').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('ERP材料对应失败')
    expect(wrapper.text()).toContain('无需重新上传')
    expect(wrapper.findAll('button').some(item => item.text() === '开始识别')).toBe(false)
    expect(api.upload).toHaveBeenCalledTimes(1)
    expectNoBusinessCreation()
  })

  it('材料AI对应先保存当前稿，以最新版本查询，保留两个表单再应用新材料结果', async () => {
    navigation.query = { importId: 'import-1' }
    const wrapper = await render()
    const task = { task_number: '人工确认单号' }, boms = [{ product_key: 'p1', sections: [{ title: '五金件', lines: [{ unit_consumption: '人工用量' }] }] }]
    await editTask(wrapper, task); await editBom(wrapper, boms)
    const taskMount = wrapper.get('[data-testid="task-form"]').attributes('data-mount-id')
    const bomMount = wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')
    const updated = { ...taskResults.main, boms: [{ product_key: 'p1', lines: [{ line_key: 'l1', erp_match: { status: 'MATCHED' } }] }] }
    api.match.mockResolvedValue(response({ result: updated, review_draft: { task_payload: task, bom_plans: boms } }, '"matched-v4"'))
    wrapper.findComponent(BomFormStub).vm.$emit('match-materials')
    await flushPromises()
    expect(api.review).toHaveBeenCalledWith('import-1', { task_key: 'main', task_payload: task, bom_plans: boms }, '"v2"')
    expect(api.match).toHaveBeenCalledWith('import-1', '"v3"')
    expect(api.review.mock.invocationCallOrder[0]).toBeLessThan(api.match.mock.invocationCallOrder[0]!)
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task)
    expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(boms)
    expect(wrapper.get('[data-testid="task-form"]').attributes('data-mount-id')).toBe(taskMount)
    expect(wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')).toBe(bomMount)
    expect(child.applyMatches).toHaveBeenCalledWith(updated)
    expect(api.remap).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })

  it('材料AI请求期间禁用编辑和重复请求，失败显示原因并保留人工核对稿', async () => {
    navigation.query = { importId: 'import-1' }
    const wrapper = await render()
    const boms = [{ product_key: 'p1', sections: [], pending_lines: [{ ai_original_text: '人工原文' }] }]
    await editBom(wrapper, boms)
    let reject!: (error: Error) => void
    api.match.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    wrapper.findComponent(BomFormStub).vm.$emit('match-materials'); await flushPromises()
    expect(wrapper.findComponent(BomFormStub).props('disabled')).toBe(true)
    expect(wrapper.findComponent(TaskFormStub).props('disabled')).toBe(true)
    wrapper.findComponent(BomFormStub).vm.$emit('match-materials'); await flushPromises()
    expect(api.match).toHaveBeenCalledTimes(1)
    reject(new Error('ERP候选查询超时')); await flushPromises()
    expect(wrapper.text()).toContain('ERP候选查询超时')
    expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(boms)
    expect(wrapper.findComponent(BomFormStub).props('matchingMaterials')).toBe(false)
    expect(child.applyMatches).not.toHaveBeenCalled()
    expectNoBusinessCreation()
  })

  it('当前核对稿保存失败时不启动材料AI请求', async () => {
    navigation.query = { importId: 'import-1' }
    const wrapper = await render(); await editTask(wrapper, { task_number: '未保存任务' })
    api.review.mockRejectedValueOnce(new Error('保存失败，版本冲突'))
    wrapper.findComponent(BomFormStub).vm.$emit('match-materials'); await flushPromises()
    expect(api.match).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('保存失败，版本冲突')
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual({ task_number: '未保存任务' })
  })

  it('材料对应失败只读恢复新版本，重试使用新ETag且不重建人工稿', async () => {
    navigation.query = { importId: 'import-1' }
    const wrapper = await render()
    const task = { task_number: '保留人工单号' }, boms = [{ product_key: 'p1', sections: [], pending_lines: [{ ai_original_text: '保留人工原文' }] }]
    await editTask(wrapper, task); await editBom(wrapper, boms)
    const mounted = wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')
    api.match.mockRejectedValueOnce(new Error('AI网络暂时不可用'))
    api.fetch.mockResolvedValueOnce(response({ review_draft: null }, '"after-failure-v4"'))
    wrapper.findComponent(BomFormStub).vm.$emit('match-materials'); await flushPromises()
    expect(wrapper.text()).toContain('AI网络暂时不可用')
    expect(api.fetch).toHaveBeenLastCalledWith('import-1')
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task)
    expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(boms)
    expect(wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')).toBe(mounted)
    wrapper.findComponent(BomFormStub).vm.$emit('match-materials'); await flushPromises()
    expect(api.match).toHaveBeenNthCalledWith(2, 'import-1', '"after-failure-v4"')
    expect(wrapper.text()).not.toContain('AI网络暂时不可用')
  })

  it('材料对应失败且状态刷新失败时保留原错误并提示刷新后重试', async () => {
    navigation.query = { importId: 'import-1' }
    const wrapper = await render(); const task = { task_number: '人工未丢失' }
    await editTask(wrapper, task)
    api.match.mockRejectedValueOnce(new Error('AI请求超时'))
    api.fetch.mockRejectedValueOnce(new Error('网络断开'))
    wrapper.findComponent(BomFormStub).vm.$emit('match-materials'); await flushPromises()
    expect(wrapper.text()).toContain('AI请求超时')
    expect(wrapper.text()).toContain('请刷新状态后重试材料对应')
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task)
    expect(wrapper.findComponent(BomFormStub).props('matchingMaterials')).toBe(false)
    expect(child.applyMatches).not.toHaveBeenCalled()
  })
  it('配置收进按钮弹窗，主页不显示 Key；弹窗只显示已保存 Key 的末四位', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('AI 生产任务导入'); expect(wrapper.find('[data-testid="config-dialog"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('••••1234'); expect(wrapper.text()).not.toContain('sha256:abcd')
    await button(wrapper, 'OpenAI 配置').trigger('click')
    expect(wrapper.get('[data-testid="config-dialog"]').text()).toContain('••••1234')
    const key = wrapper.get<HTMLInputElement>('input[aria-label="完整 API Key"]')
    expect(key.element.value).toBe(''); expect(key.attributes('type')).toBe('password')
    expect(wrapper.get<HTMLInputElement>('input[aria-label="Key 标签"]').element.value).toBe('主 Key')
    expect(api.save).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('选择表格只准备上传，明确点击开始识别后才调用 AI', async () => {
    const wrapper = await render(); await selectFile(wrapper)
    expect(wrapper.text()).toContain('task.xlsx'); expect(button(wrapper, '开始识别').attributes('disabled')).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1000); await flushPromises()
    expect(api.upload).not.toHaveBeenCalled(); expectNoBusinessCreation()
    await button(wrapper, '开始识别').trigger('click'); await flushPromises()
    expect(api.upload).toHaveBeenCalledTimes(1); expect(wrapper.find('.selected-file').exists()).toBe(false)
    expectNoBusinessCreation()
  })
  it.each(['取消', '关闭'])('%s 配置后丢弃未保存输入，重开恢复已保存配置且 Key 仍为空', async action => {
    const wrapper = await render(); await button(wrapper, 'OpenAI 配置').trigger('click')
    await wrapper.get('input[aria-label="Key 标签"]').setValue('未保存名称')
    await wrapper.get('input[aria-label="完整 API Key"]').setValue('test-new-key-value')
    await wrapper.get('button[aria-label="显示 Key"]').trigger('click')
    expect(wrapper.get('input[aria-label="完整 API Key"]').attributes('type')).toBe('text')
    await button(wrapper, action).trigger('click')
    expect(wrapper.find('[data-testid="config-dialog"]').exists()).toBe(false); expect(api.save).not.toHaveBeenCalled()
    await button(wrapper, 'OpenAI 配置').trigger('click')
    expect(wrapper.get<HTMLInputElement>('input[aria-label="Key 标签"]').element.value).toBe('主 Key')
    expect(wrapper.get<HTMLInputElement>('input[aria-label="完整 API Key"]').element.value).toBe('')
    expect(wrapper.get('input[aria-label="完整 API Key"]').attributes('type')).toBe('password')
  })
  it('已有配置允许 Key 留空保存元数据，并携带原配置版本', async () => {
    const wrapper = await render(); await button(wrapper, 'OpenAI 配置').trigger('click')
    await wrapper.get('input[aria-label="Key 标签"]').setValue(' 更新名称 ')
    await button(wrapper, '保存配置').trigger('click'); await flushPromises()
    expect(api.save).toHaveBeenCalledExactlyOnceWith({ label: '更新名称', provider: 'openai', model: 'gpt-6.1-sol', document_reasoning_effort: 'auto', material_reasoning_effort: 'auto', base_url: '', api_key: '' }, '"c1"', 'config-1')
    expect(wrapper.find('[data-testid="config-dialog"]').exists()).toBe(false); expectNoBusinessCreation()
  })
  it('旧配置显示各步骤既有自动强度，模型变更同步更新自动说明', async () => {
    const wrapper = await render()
    await button(wrapper, 'OpenAI 配置').trigger('click')
    const document = effortSelect(wrapper, '读表推理强度')
    const materials = effortSelect(wrapper, '对应 ERP 材料推理强度')
    for (const select of [document, materials]) {
      expect(select.props('modelValue')).toBe('auto')
      expect(select.findAllComponents(ElOption).map(option => option.props('value'))).toEqual(['auto', 'low', 'medium', 'high', 'xhigh', 'max'])
    }
    expect(document.findAllComponents(ElOption)[0]!.props('label')).toBe('自动（低）')
    expect(materials.findAllComponents(ElOption)[0]!.props('label')).toBe('自动（中）')
    await wrapper.get('input[aria-label="模型"]').setValue('other-model')
    expect(document.findAllComponents(ElOption)[0]!.props('label')).toBe('自动（模型默认）')
    expect(materials.findAllComponents(ElOption)[0]!.props('label')).toBe('自动（模型默认）')
  })
  it('分别修改两步强度，无需再填 Key，重开读取保存值，取消不会覆盖它们', async () => {
    const saved = { ...config, document_reasoning_effort: 'xhigh', material_reasoning_effort: 'low' }
    api.save.mockResolvedValueOnce({ data: saved, etag: '"c2"' })
    const wrapper = await render()
    await button(wrapper, 'OpenAI 配置').trigger('click')
    effortSelect(wrapper, '读表推理强度').vm.$emit('update:modelValue', 'xhigh')
    effortSelect(wrapper, '对应 ERP 材料推理强度').vm.$emit('update:modelValue', 'low')
    await button(wrapper, '保存配置').trigger('click')
    await flushPromises()
    expect(api.save).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ document_reasoning_effort: 'xhigh', material_reasoning_effort: 'low', api_key: '' }), '"c1"', 'config-1')
    await button(wrapper, 'OpenAI 配置').trigger('click')
    expect(effortSelect(wrapper, '读表推理强度').props('modelValue')).toBe('xhigh')
    effortSelect(wrapper, '读表推理强度').vm.$emit('update:modelValue', 'high')
    await button(wrapper, '取消').trigger('click')
    await button(wrapper, 'OpenAI 配置').trigger('click')
    expect(effortSelect(wrapper, '读表推理强度').props('modelValue')).toBe('xhigh')
    expect(effortSelect(wrapper, '对应 ERP 材料推理强度').props('modelValue')).toBe('low')
  })
  it('配置保存失败保留弹窗与输入，可直接重试', async () => {
    api.save.mockRejectedValueOnce(new Error('保存失败'))
    const wrapper = await render(); await button(wrapper, 'OpenAI 配置').trigger('click')
    await wrapper.get('input[aria-label="完整 API Key"]').setValue('test-new-key-value')
    await button(wrapper, '保存配置').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-testid="config-dialog"]').text()).toContain('OpenAI 配置保存失败，当前输入仍保留')
    expect(wrapper.get<HTMLInputElement>('input[aria-label="完整 API Key"]').element.value).toBe('test-new-key-value')
    expect(wrapper.get('input[aria-label="完整 API Key"]').attributes('type')).toBe('password')
    await button(wrapper, '保存配置').trigger('click'); await flushPromises()
    expect(api.save).toHaveBeenCalledTimes(2); expect(wrapper.find('[data-testid="config-dialog"]').exists()).toBe(false)
  })
  it('首次配置缺少 Key 时不发送保存请求', async () => {
    api.config.mockResolvedValue({ data: { ...config, id: '', key_configured: false, key_last4: '' }, etag: '' })
    const wrapper = await render(); await button(wrapper, 'OpenAI 配置').trigger('click')
    await button(wrapper, '保存配置').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('首次配置必须输入完整 API Key'); expect(api.save).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="config-dialog"]').exists()).toBe(true)
  })
  it('配置保存进行中禁用取消、隐藏关闭入口，保存成功再关闭', async () => {
    let resolveSave!: (value: { data: typeof config; etag: string }) => void
    api.save.mockImplementationOnce(() => new Promise(done => { resolveSave = done }))
    const wrapper = await render(); await button(wrapper, 'OpenAI 配置').trigger('click')
    await button(wrapper, '保存配置').trigger('click'); await flushPromises()
    expect(button(wrapper, '取消').attributes('disabled')).toBeDefined()
    expect(wrapper.find('button[aria-label="关闭配置"]').exists()).toBe(false)
    await button(wrapper, '取消').trigger('click')
    expect(wrapper.find('[data-testid="config-dialog"]').exists()).toBe(true)
    resolveSave({ data: config, etag: '"c2"' }); await flushPromises()
    expect(wrapper.find('[data-testid="config-dialog"]').exists()).toBe(false)
  })
  it('拒绝非表格；成功上传显示两区块，不调用业务创建', async () => {
    const wrapper = await render()
    await selectFile(wrapper, 'task.txt'); expect(wrapper.text()).toContain('只支持 XLSX 或 XLS 文件'); expect(api.upload).not.toHaveBeenCalled()
    await selectFile(wrapper); await button(wrapper, '开始识别').trigger('click'); await flushPromises()
    expect(api.upload).toHaveBeenCalledTimes(1); expect(wrapper.find('[data-testid="task-form"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bom-form"]').exists()).toBe(true)
    expect(navigation.replace).toHaveBeenCalledWith({ query: { importId: 'import-1' } })
    expect(wrapper.find('textarea[aria-label="生产任务草稿 JSON"]').exists()).toBe(false); expectNoBusinessCreation()
  })
  it('等待期间阻止重复识别，失败保留选中文件', async () => {
    let reject!: (error: unknown) => void; api.upload.mockReturnValue(new Promise((_, fail) => { reject = fail }))
    const wrapper = await render(); const input = await selectFile(wrapper)
    const start = button(wrapper, '开始识别'); await start.trigger('click'); await flushPromises(); await start.trigger('click')
    expect(api.upload).toHaveBeenCalledTimes(1); expect(input.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('正在识别，完成后自动保存记录')
    reject(new AxiosError('timeout', 'ECONNABORTED')); await flushPromises()
    expect(wrapper.text()).toContain('等待识别结果超时'); expect((input.element as HTMLInputElement).files?.[0]?.name).toBe('task.xlsx'); expectNoBusinessCreation()
  })
  it('链接重开读取已保存的任务和 BOM 核对稿，不再次调用 AI', async () => {
    navigation.query = { importId: 'import-1' }
    const task = { task_number: 'HT人工核对', products: [{ quantity: '450' }] }, boms = [{ product_key: 'p1', sections: [{ title: '管材类' }] }]
    api.fetch.mockResolvedValue(response({ review_draft: { task_payload: task, bom_plans: boms } }))
    const wrapper = await render()
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task); expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(boms)
    expect(api.fetch).toHaveBeenCalledWith('import-1'); expect(api.upload).not.toHaveBeenCalled(); expect(api.review).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('编辑自动保存，刷新使用最新版本且不覆盖任务与 BOM 修改', async () => {
    navigation.query = { importId: 'import-1' }; const wrapper = await render()
    const task = { task_number: 'HT26149-1', order_date: '2026-11-01' }, boms = [{ product_key: 'p1', source_text: '人工补充规格' }]
    await editTask(wrapper, task); await editBom(wrapper, boms); await vi.advanceTimersByTimeAsync(900); await flushPromises()
    expect(api.review).toHaveBeenCalledWith('import-1', { task_key: 'main', task_payload: task, bom_plans: boms }, '"v2"'); expect(wrapper.text()).toContain('已保存')
    api.fetch.mockResolvedValue(response({ review_draft: { task_payload: { task_number: '旧编号' }, bom_plans: [] } }, '"v4"'))
    await button(wrapper, '刷新状态').trigger('click'); await flushPromises()
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task); expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(boms)
    expect(api.upload).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('保存失败保留编辑内容，并阻止刷新、创建和页面离开', async () => {
    navigation.query = { importId: 'import-1' }; const wrapper = await render(); const task = { task_number: 'HT26149-2' }
    api.review.mockRejectedValue(new Error('连接失败，修改未保存'))
    await editTask(wrapper, task); await button(wrapper, '保存修改').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('连接失败，修改未保存'); expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task)
    await button(wrapper, '刷新状态').trigger('click'); await flushPromises(); expect(api.fetch).toHaveBeenCalledTimes(1)
    await button(wrapper, '确认创建生产任务草稿').trigger('click'); await flushPromises()
    expectNoBusinessCreation(); expect(child.taskPayload).not.toHaveBeenCalled(); expect(await navigation.leave?.()).toBe(false)
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task)
  })
  it('保存进行时的新编辑仍保留，并按最新内容再保存', async () => {
    navigation.query = { importId: 'import-1' }; let resolve!: (value: ReturnType<typeof response>) => void
    api.review.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = await render(); await editTask(wrapper, { task_number: 'HT26149-1' })
    await button(wrapper, '保存修改').trigger('click'); await flushPromises(); await editTask(wrapper, { task_number: 'HT26149-2' })
    resolve(response({ review_draft: { task_payload: { task_number: 'HT26149-1' }, bom_plans: null } }, '"v3"')); await flushPromises()
    expect(wrapper.text()).toContain('有未保存修改'); expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual({ task_number: 'HT26149-2' })
    await vi.advanceTimersByTimeAsync(900); await flushPromises()
    expect(api.review).toHaveBeenLastCalledWith('import-1', { task_key: 'main', task_payload: { task_number: 'HT26149-2' }, bom_plans: null }, '"v3"'); expectNoBusinessCreation()
  })
  it('创建前保存尚未返回时，连续点击只能创建一次任务', async () => {
    navigation.query = { importId: 'import-1' }
    let resolve!: (value: ReturnType<typeof response>) => void
    api.review.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    api.createTask.mockResolvedValue(response({ state: 'TASK_DRAFT', task_id: 'task-1' }, '"v4"'))
    const wrapper = await render(); await editTask(wrapper, { task_number: 'HT26149' })
    const create = button(wrapper, '确认创建生产任务草稿')
    await create.trigger('click'); await flushPromises(); await create.trigger('click'); await flushPromises()
    resolve(response({ review_draft: { task_payload: { task_number: 'HT26149' }, bom_plans: null } }, '"v3"')); await flushPromises()
    expect(api.createTask).toHaveBeenCalledTimes(1)
    expect(api.createBoms).not.toHaveBeenCalled()
  })
  it('BOM 创建前保存尚未返回时，连续点击只能创建一次 BOM', async () => {
    navigation.query = { importId: 'import-1' }
    api.fetch.mockResolvedValue(response({ task_id: 'task-1', task_status: 'READY' }))
    let resolve!: (value: ReturnType<typeof response>) => void
    api.review.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    api.createBoms.mockResolvedValue(response({ state: 'BOM_PENDING', task_id: 'task-1', task_status: 'READY', bom_ids: ['bom-1'] }, '"v4"'))
    const wrapper = await render(); const plans = [{ product_key: 'p1', sections: [] }]
    await editBom(wrapper, plans)
    const create = button(wrapper, '确认创建 BOM')
    await create.trigger('click'); await flushPromises(); await create.trigger('click'); await flushPromises()
    resolve(response({ task_id: 'task-1', task_status: 'READY', review_draft: { task_payload: null, bom_plans: plans } }, '"v3"')); await flushPromises()
    expect(api.createBoms).toHaveBeenCalledTimes(1)
    expect(api.createTask).not.toHaveBeenCalled()
  })
  it('进行中记录首次取得结果才显示两区块，刷新不重新识别', async () => {
    navigation.query = { importId: 'import-1' }; api.fetch.mockResolvedValueOnce(response({ state: 'RECOGNIZING', result: {} })).mockResolvedValue(response())
    const wrapper = await render(); expect(wrapper.find('[data-testid="task-form"]').exists()).toBe(false)
    await button(wrapper, '刷新状态').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-testid="task-form"]').exists()).toBe(true); expect(wrapper.find('[data-testid="bom-form"]').exists()).toBe(true)
    expect(api.upload).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('切换任务先保存当前两个核对稿，等待期间不切换，成功后重建各自表单', async () => {
    navigation.query = { importId: 'import-1' }; api.fetch.mockResolvedValue(multiResponse())
    let resolveSave!: (value: ReturnType<typeof multiResponse>) => void
    api.review.mockImplementationOnce(() => new Promise(done => { resolveSave = done }))
    const nextDraft = { task_payload: { task_number: 'HT26150-已核对' }, bom_plans: [{ product_key: 'second-product', sections: [] }] }
    api.select.mockResolvedValue(multiResponse('second', { review_draft: nextDraft }, '"v4"'))
    const wrapper = await render()
    const oldTask = wrapper.get('[data-testid="task-form"]').attributes('data-mount-id')
    const oldBom = wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')
    const task = { task_number: 'HT26149-人工核对' }, boms = [{ product_key: 'main-product', sections: [{ title: '管材类' }] }]
    await editTask(wrapper, task); await editBom(wrapper, boms)
    await taskTab(wrapper, 'second').trigger('click'); await flushPromises()
    await taskTab(wrapper, 'second').trigger('click'); await flushPromises()
    expect(api.review).toHaveBeenCalledTimes(1)
    expect(api.review).toHaveBeenCalledWith('import-1', { task_key: 'main', task_payload: task, bom_plans: boms }, '"v2"')
    expect(api.select).not.toHaveBeenCalled(); expect(selectedTask(wrapper)).toBe('main')
    expect(taskTab(wrapper, 'second').attributes('disabled')).toBeDefined()
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task)
    resolveSave(multiResponse('main', { review_draft: { task_payload: task, bom_plans: boms } }, '"v3"')); await flushPromises()
    expect(api.select).toHaveBeenCalledExactlyOnceWith('import-1', 'second', '"v3"')
    expect(selectedTask(wrapper)).toBe('second')
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(nextDraft.task_payload)
    expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(nextDraft.bom_plans)
    expect(wrapper.findComponent(TaskFormStub).props('result')).toMatchObject(taskResults.second)
    expect(wrapper.findComponent(BomFormStub).props('result')).toMatchObject(taskResults.second)
    expect(wrapper.get('[data-testid="task-form"]').attributes('data-mount-id')).not.toBe(oldTask)
    expect(wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')).not.toBe(oldBom)
    expect(api.upload).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it.each(['save', 'select'])('切换任务时 %s 失败保留当前任务、两个核对稿及表单实例', async phase => {
    navigation.query = { importId: 'import-1' }; api.fetch.mockResolvedValue(multiResponse())
    const task = { task_number: 'HT26149-人工核对' }, boms = [{ product_key: 'main-product', sections: [] }]
    api.review.mockResolvedValue(multiResponse('main', { review_draft: { task_payload: task, bom_plans: boms } }, '"v3"'))
    if (phase === 'save') api.review.mockRejectedValue(new Error('当前任务保存失败'))
    else api.select.mockRejectedValue(new Error('任务切换失败'))
    const wrapper = await render()
    const oldTask = wrapper.get('[data-testid="task-form"]').attributes('data-mount-id'), oldBom = wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')
    await editTask(wrapper, task); await editBom(wrapper, boms)
    await taskTab(wrapper, 'second').trigger('click'); await flushPromises()
    expect(selectedTask(wrapper)).toBe('main')
    expect(wrapper.text()).toContain(phase === 'save' ? '当前任务保存失败' : '任务切换失败')
    expect(api.select).toHaveBeenCalledTimes(phase === 'save' ? 0 : 1)
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task); expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(boms)
    expect(wrapper.get('[data-testid="task-form"]').attributes('data-mount-id')).toBe(oldTask); expect(wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')).toBe(oldBom)
    expectNoBusinessCreation()
  })
  it.each(['main', 'second'] as const)('重开多任务记录恢复 %s 对应的结果和核对稿，不重新识别', async taskKey => {
    navigation.query = { importId: 'import-1' }
    const task = { task_number: `${taskKey}-已核对` }, boms = [{ product_key: `${taskKey}-product`, sections: [{ title: '五金类' }] }]
    api.fetch.mockResolvedValue(multiResponse(taskKey, { review_draft: { task_key: taskKey, task_payload: task, bom_plans: boms } }))
    const wrapper = await render()
    expect(selectedTask(wrapper)).toBe(taskKey)
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task); expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(boms)
    expect(wrapper.findComponent(TaskFormStub).props('result')).toMatchObject(taskResults[taskKey])
    expect(wrapper.findComponent(BomFormStub).props('result')).toMatchObject(taskResults[taskKey])
    expect(api.fetch).toHaveBeenCalledExactlyOnceWith('import-1')
    expect(api.upload).not.toHaveBeenCalled(); expect(api.select).not.toHaveBeenCalled(); expect(api.review).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it.each(['task', 'bom'])('创建 %s 时传递当前选中的任务键', async kind => {
    navigation.query = { importId: 'import-1' }
    const task = { task_number: 'HT26150-已核对' }, boms = [{ product_key: 'second-product', sections: [] }]
    const existingTask = kind === 'bom' ? { task_id: 'task-second', task_status: 'READY', state: 'TASK_DRAFT' } : {}
    api.fetch.mockResolvedValue(multiResponse('second', { ...existingTask, review_draft: { task_payload: task, bom_plans: boms } }))
    api.createTask.mockResolvedValue(multiResponse('second', { task_id: 'task-second', state: 'TASK_DRAFT' }, '"v3"'))
    api.createBoms.mockResolvedValue(multiResponse('second', { ...existingTask, state: 'BOM_PENDING', bom_ids: ['bom-second'] }, '"v3"'))
    const wrapper = await render()
    await button(wrapper, kind === 'task' ? '确认创建生产任务草稿' : '确认创建 BOM').trigger('click'); await flushPromises()
    if (kind === 'task') {
      expect(api.createTask).toHaveBeenCalledExactlyOnceWith('import-1', task, '"v2"', 'second'); expect(api.createBoms).not.toHaveBeenCalled()
    } else {
      expect(api.createBoms).toHaveBeenCalledExactlyOnceWith('import-1', boms, '"v2"', 'second'); expect(api.createTask).not.toHaveBeenCalled()
    }
    expect(api.upload).not.toHaveBeenCalled(); expect(api.review).not.toHaveBeenCalled()
  })
  it('重新对应同一记录时先保存旧稿，再重建两个表单使用新版字段来源', async () => {
    navigation.query = { importId: 'import-1' }; const wrapper = await render()
    const oldTask = wrapper.get('[data-testid="task-form"]').attributes('data-mount-id'), oldBom = wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')
    const reviewed = { task_number: 'HT26149-1' }; await editTask(wrapper, reviewed)
    api.remap.mockResolvedValue(response({ result: { task: { task_number: { value: 'HT26150' } }, products: [] }, review_draft: null }, '"v4"'))
    await button(wrapper, '重新对应 ERP 字段').trigger('click'); await flushPromises()
    expect(api.review).toHaveBeenCalledWith('import-1', { task_key: 'main', task_payload: reviewed, bom_plans: null }, '"v2"')
    expect(api.remap).toHaveBeenCalledWith('import-1', '"v3"')
    expect(wrapper.get('[data-testid="task-form"]').attributes('data-mount-id')).not.toBe(oldTask); expect(wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')).not.toBe(oldBom)
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toBeNull()
    expect(wrapper.get('[data-testid="task-form"]').attributes('data-initial-task')).toBe('HT26150')
    expect(api.upload).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('重新对应失败后读取最新状态，但保留原核对稿和表单实例', async () => {
    navigation.query = { importId: 'import-1' }; const wrapper = await render()
    const task = { task_number: 'HT26149-2' }, boms = [{ product_key: 'p1', sections: [] }]
    await editTask(wrapper, task); await editBom(wrapper, boms)
    const oldTask = wrapper.get('[data-testid="task-form"]').attributes('data-mount-id'), oldBom = wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')
    api.remap.mockRejectedValue(new Error('字段对照失败，原资料保留'))
    await button(wrapper, '重新对应 ERP 字段').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('字段对照失败，原资料保留')
    expect(api.fetch).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="task-form"]').attributes('data-mount-id')).toBe(oldTask); expect(wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')).toBe(oldBom)
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task); expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(boms)
    expect(api.upload).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('重新对应等待旧稿保存时，连续确认只调用一次 AI', async () => {
    navigation.query = { importId: 'import-1' }
    let resolve!: (value: ReturnType<typeof response>) => void
    api.review.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = await render(); const task = { task_number: 'HT26149-1' }; await editTask(wrapper, task)
    const remap = button(wrapper, '重新对应 ERP 字段')
    await remap.trigger('click'); await flushPromises(); await remap.trigger('click'); await flushPromises()
    resolve(response({ review_draft: { task_payload: task, bom_plans: null } }, '"v3"')); await flushPromises()
    expect(api.remap).toHaveBeenCalledTimes(1)
    expectNoBusinessCreation()
  })
  it('取消重新对应不调用 AI 或改写已编辑表单', async () => {
    navigation.query = { importId: 'import-1' }; const wrapper = await render(); const task = { task_number: 'HT26149-3' }
    await editTask(wrapper, task); vi.mocked(ElMessageBox.confirm).mockRejectedValue('cancel')
    await button(wrapper, '重新对应 ERP 字段').trigger('click'); await flushPromises()
    expect(api.remap).not.toHaveBeenCalled(); expect(api.review).not.toHaveBeenCalled()
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task); expectNoBusinessCreation()
  })
  it('恢复上次核对稿前保存当前修改，成功后重建任务与 BOM 表单', async () => {
    navigation.query = { importId: 'import-1' }
    api.fetch.mockResolvedValue(response({ has_previous_recognition: true, has_created_tasks: false }))
    let resolveSave!: (value: ReturnType<typeof response>) => void
    api.review.mockImplementationOnce(() => new Promise(done => { resolveSave = done }))
    const previousTask = { task_number: 'HT26148-上一版' }, previousBoms = [{ product_key: 'previous-product', sections: [] }]
    api.restore.mockResolvedValue(response({ result: { task: { task_number: { value: 'HT26148' } }, products: [] }, review_draft: { task_payload: previousTask, bom_plans: previousBoms } }, '"v4"'))
    const wrapper = await render()
    const oldTask = wrapper.get('[data-testid="task-form"]').attributes('data-mount-id'), oldBom = wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')
    const task = { task_number: 'HT26149-当前修改' }; await editTask(wrapper, task)
    await button(wrapper, '恢复上次核对稿').trigger('click'); await flushPromises()
    expect(api.review).toHaveBeenCalledWith('import-1', { task_key: 'main', task_payload: task, bom_plans: null }, '"v2"')
    expect(api.restore).not.toHaveBeenCalled()
    resolveSave(response({ has_previous_recognition: true, review_draft: { task_payload: task, bom_plans: null } }, '"v3"')); await flushPromises()
    expect(api.restore).toHaveBeenCalledExactlyOnceWith('import-1', '"v3"')
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(previousTask); expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(previousBoms)
    expect(wrapper.get('[data-testid="task-form"]').attributes('data-mount-id')).not.toBe(oldTask); expect(wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')).not.toBe(oldBom)
    expect(wrapper.get('[data-testid="task-form"]').attributes('data-initial-task')).toBe('HT26148-上一版')
    expect(api.upload).not.toHaveBeenCalled(); expect(api.remap).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('恢复上次核对稿失败保留当前两个核对稿和表单实例', async () => {
    navigation.query = { importId: 'import-1' }
    const task = { task_number: 'HT26149-当前核对稿' }, boms = [{ product_key: 'current-product', sections: [] }]
    api.fetch.mockResolvedValue(response({ has_previous_recognition: true, review_draft: { task_payload: task, bom_plans: boms } }))
    api.restore.mockRejectedValue(new Error('上一版核对稿恢复失败'))
    const wrapper = await render()
    const oldTask = wrapper.get('[data-testid="task-form"]').attributes('data-mount-id'), oldBom = wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')
    await button(wrapper, '恢复上次核对稿').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('上一版核对稿恢复失败')
    expect(wrapper.findComponent(TaskFormStub).props('modelValue')).toEqual(task); expect(wrapper.findComponent(BomFormStub).props('modelValue')).toEqual(boms)
    expect(wrapper.get('[data-testid="task-form"]').attributes('data-mount-id')).toBe(oldTask); expect(wrapper.get('[data-testid="bom-form"]').attributes('data-mount-id')).toBe(oldBom)
    expect(api.upload).not.toHaveBeenCalled(); expect(api.remap).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('文件中任何任务已创建后不再显示恢复上次核对稿入口', async () => {
    navigation.query = { importId: 'import-1' }
    api.fetch.mockResolvedValue(multiResponse('second', { has_previous_recognition: true, has_created_tasks: true }))
    const wrapper = await render()
    expect(wrapper.findComponent(TaskFormStub).exists()).toBe(true)
    expect(wrapper.findAll('button').some(item => item.text() === '恢复上次核对稿')).toBe(false)
    expect(api.restore).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('从识别记录重开只读取原记录，已创建任务图片跳转现有编辑页', async () => {
    const wrapper = await render(); await button(wrapper, '识别记录').trigger('click'); await flushPromises(); expect(api.list).toHaveBeenCalledWith(0)
    api.fetch.mockResolvedValue(response({ task_id: 'task-1', task_number: 'HT26149', task_status: 'DRAFT' }))
    await button(wrapper, '打开').trigger('click'); await flushPromises()
    expect(api.fetch).toHaveBeenCalledWith('import-1'); expect(api.upload).not.toHaveBeenCalled(); expect(wrapper.findComponent(TaskFormStub).exists()).toBe(false)
    await button(wrapper, '打开任务 / 上传图片').trigger('click')
    expect(navigation.push).toHaveBeenCalledWith({ name: 'production-task-edit', params: { taskId: 'task-1' } }); expectNoBusinessCreation()
  })
  it('取消删除不调用删除接口或业务创建', async () => {
    const wrapper = await render(); await button(wrapper, '识别记录').trigger('click'); await flushPromises()
    vi.mocked(ElMessageBox.confirm).mockRejectedValue('cancel'); await button(wrapper, '删除').trigger('click'); await flushPromises()
    expect(api.remove).not.toHaveBeenCalled(); expect(api.fetch).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('删除当前识别记录使用最新版本并清空预览，保留业务创建边界', async () => {
    navigation.query = { importId: 'import-1', other: 'keep' }
    api.fetch.mockResolvedValue(response({ task_id: 'task-1', task_status: 'READY', bom_ids: ['bom-1'] }, '"latest"'))
    const wrapper = await render(); await button(wrapper, '识别记录').trigger('click'); await flushPromises(); api.list.mockResolvedValue({ count: 0, results: [] })
    await button(wrapper, '删除').trigger('click'); await flushPromises()
    expect(api.remove).toHaveBeenCalledWith('import-1', '"latest"'); expect(navigation.replace).toHaveBeenLastCalledWith({ query: { other: 'keep' } })
    expect(wrapper.find('[data-testid="bom-form"]').exists()).toBe(false); expect(wrapper.text()).toContain('上传一个生产任务表格')
    expect(api.upload).not.toHaveBeenCalled(); expectNoBusinessCreation()
  })
  it('删除失败保留当前记录及核对表单', async () => {
    navigation.query = { importId: 'import-1' }; const wrapper = await render(); await button(wrapper, '识别记录').trigger('click'); await flushPromises()
    api.remove.mockRejectedValue(new Error('版本冲突，请刷新')); await button(wrapper, '删除').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('版本冲突，请刷新'); expect(wrapper.find('[data-testid="task-form"]').exists()).toBe(true)
    expect(navigation.replace).not.toHaveBeenCalledWith({ query: {} }); expectNoBusinessCreation()
  })
})
