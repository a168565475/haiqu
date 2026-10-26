import { effectScope, type EffectScope } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BomHardwareMaterial, BomHardwareMaterialGroup, PaginatedBomHardwareMaterials } from '@/types/bom'
import { useBomMaterialCandidates } from './useBomMaterialCandidates'

const material = (id: string) => ({ id, material_name: id }) as BomHardwareMaterial
const result = (...ids: string[]): PaginatedBomHardwareMaterials => ({ data: ids.map(material), meta: { page: 1, page_size: 50, total: ids.length, total_pages: 1 } })
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const scopes: EffectScope[] = []
function setup() {
  const scope = effectScope(); scopes.push(scope)
  const fetchCandidates = vi.fn<(query: unknown) => Promise<PaginatedBomHardwareMaterials>>().mockResolvedValue(result('a', 'b'))
  const fetchGroups = vi.fn<() => Promise<BomHardwareMaterialGroup[]>>().mockResolvedValue([
    { material_name: '钢管', count: 2, pinyin_search: 'gang guan gg' }, { material_name: '纸箱', count: 1, pinyin_search: 'zhi xiang zx' },
  ])
  const picker = scope.run(() => useBomMaterialCandidates({ label: '五金', fetchCandidates, fetchGroups,
    mergeCandidates: (rows, query) => [material(`pending:${query.q || ''}`), ...rows],
    errorMessage: (_error, fallback) => fallback,
  }))!
  return { picker, fetchCandidates, fetchGroups, scope }
}
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()) })

describe('BOM 候选共用状态', () => {
  it('关闭后重开，迟到的 closed 事件不清空新选择或请求', async () => {
    const { picker, fetchCandidates } = setup()
    await picker.open()
    picker.visible.value = false
    const pending = deferred<PaginatedBomHardwareMaterials>()
    fetchCandidates.mockReturnValueOnce(pending.promise)
    const reopening = picker.open()
    picker.toggleCandidate(material('new-choice'), true)
    picker.onClosed()
    expect(picker.visible.value).toBe(true)
    expect(picker.loading.value).toBe(true)
    expect(picker.selectedCount.value).toBe(1)
    pending.resolve(result('new-page')); await reopening
    expect(picker.candidates.value.map(item => item.id)).toEqual(['pending:', 'new-page'])
  })

  it('旧候选成功不能替换新搜索，并按发起时的查询合并临时材料', async () => {
    const { picker, fetchCandidates } = setup()
    const old = deferred<PaginatedBomHardwareMaterials>(), latest = deferred<PaginatedBomHardwareMaterials>()
    fetchCandidates.mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise)
    const opening = picker.open()
    picker.keyword.value = '  steel  '
    const search = picker.search()
    old.resolve(result('old')); await opening
    expect(picker.candidates.value).toEqual([])
    expect(picker.loading.value).toBe(true)
    picker.keyword.value = '尚未查询的新输入'
    latest.resolve(result('latest')); await search
    expect(picker.candidates.value.map(item => item.id)).toEqual(['pending:steel', 'latest'])
    expect(picker.loading.value).toBe(false)
  })

  it('分组旧错误不结束新分组请求或清空新结果', async () => {
    const { picker, fetchGroups } = setup()
    const old = deferred<BomHardwareMaterialGroup[]>(), latest = deferred<BomHardwareMaterialGroup[]>()
    fetchGroups.mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise)
    const opening = picker.open(), reloading = picker.loadGroups()
    old.reject(new Error('旧错误')); await opening
    expect(picker.groupLoading.value).toBe(true)
    expect(picker.groupError.value).toBe('')
    latest.resolve([{ material_name: '新分组', count: 1, pinyin_search: '' }]); await reloading
    expect(picker.groups.value[0]?.material_name).toBe('新分组')
    expect(picker.groupLoading.value).toBe(false)
  })

  it('半选、全选和本页取消使用当前候选，保留其他页选择', async () => {
    const { picker } = setup(); await picker.open()
    picker.toggleCandidate(material('other-page'), true)
    picker.toggleRow(material('a'))
    expect(picker.pageAllSelected.value).toBe(false)
    expect(picker.pageSelectionIndeterminate.value).toBe(true)
    expect(picker.rowClass({ row: material('a') })).toBe('is-picker-selected')
    picker.togglePage(true)
    expect(picker.pageAllSelected.value).toBe(true)
    expect(picker.pageSelectionIndeterminate.value).toBe(false)
    picker.togglePage(false)
    expect(Object.keys(picker.selected.value)).toEqual(['other-page'])
    expect(picker.rowClass({ row: material('a') })).toBe('')
  })

  it('品名搜索支持拼音，关闭下拉只清过滤词、不清当前品名选择', async () => {
    const { picker } = setup(); await picker.open()
    picker.materialName.value = '钢管'
    picker.filterGroups('G G')
    expect(picker.visibleGroups.value.map(item => item.material_name)).toEqual(['钢管'])
    picker.clearGroupFilter(false)
    expect(picker.visibleGroups.value).toHaveLength(2)
    expect(picker.materialName.value).toBe('钢管')
  })

  it('关闭或卸载后的失败保持清空状态，卸载后不再启动请求', async () => {
    const { picker, fetchCandidates, fetchGroups, scope } = setup()
    const pending = deferred<PaginatedBomHardwareMaterials>()
    fetchCandidates.mockReturnValueOnce(pending.promise)
    const opening = picker.open()
    picker.visible.value = false
    scope.stop()
    pending.reject(new Error('迟到错误')); await opening
    expect(picker.error.value).toBe('')
    expect(picker.candidates.value).toEqual([])
    expect(picker.groups.value).toEqual([])
    expect(picker.loading.value).toBe(false)
    await picker.open(); await picker.loadCandidates(); await picker.loadGroups()
    expect(fetchCandidates).toHaveBeenCalledTimes(1)
    expect(fetchGroups).toHaveBeenCalledTimes(1)
  })
})
