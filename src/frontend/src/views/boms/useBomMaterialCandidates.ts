import { computed, onScopeDispose, ref, watch } from 'vue'
import type { BomHardwareMaterial, BomHardwareMaterialGroup, BomMaterialPickerQuery, PaginatedBomHardwareMaterials } from '@/types/bom'
import { matchesPinyinSearch } from '@/utils/pinyinSearch'

interface MaterialCandidateOptions {
  label: string
  fetchCandidates: (query: BomMaterialPickerQuery) => Promise<PaginatedBomHardwareMaterials>
  fetchGroups: () => Promise<BomHardwareMaterialGroup[]>
  mergeCandidates: (rows: BomHardwareMaterial[], query: BomMaterialPickerQuery) => BomHardwareMaterial[]
  errorMessage: (error: unknown, fallback: string) => string
}

export function useBomMaterialCandidates(options: MaterialCandidateOptions) {
  const visible = ref(false), loading = ref(false), error = ref('')
  const groupLoading = ref(false), groupError = ref('')
  const groups = ref<BomHardwareMaterialGroup[]>([]), groupKeyword = ref('')
  const materialName = ref(''), keyword = ref('')
  const page = ref(1), pageSize = ref(50), total = ref(0)
  const candidates = ref<BomHardwareMaterial[]>([])
  const selected = ref<Record<string, BomHardwareMaterial>>({})
  let candidateRequest = 0, groupRequest = 0, disposed = false

  const visibleGroups = computed(() => groups.value.filter(group => matchesPinyinSearch(group.material_name, group.pinyin_search, groupKeyword.value)))
  const selectedCount = computed(() => Object.keys(selected.value).length)
  const pageSelectedCount = computed(() => candidates.value.filter(item => selected.value[item.id]).length)
  const pageAllSelected = computed(() => candidates.value.length > 0 && pageSelectedCount.value === candidates.value.length)
  const pageSelectionIndeterminate = computed(() => pageSelectedCount.value > 0 && !pageAllSelected.value)

  async function loadCandidates() {
    if (disposed) return
    const request = ++candidateRequest
    const query = { page: page.value, page_size: pageSize.value, q: keyword.value.trim() || undefined, material_name: materialName.value || undefined }
    loading.value = true
    error.value = ''
    try {
      const response = await options.fetchCandidates(query)
      if (disposed || request !== candidateRequest) return
      candidates.value = options.mergeCandidates(response.data, query)
      total.value = response.meta.total
    } catch (reason) {
      if (disposed || request !== candidateRequest) return
      candidates.value = options.mergeCandidates([], query)
      total.value = 0
      error.value = options.errorMessage(reason, `${options.label}数据加载失败，请稍后重试。`)
    } finally {
      if (!disposed && request === candidateRequest) loading.value = false
    }
  }

  async function loadGroups() {
    if (disposed) return
    const request = ++groupRequest
    groupLoading.value = true
    groupError.value = ''
    try {
      const response = await options.fetchGroups()
      if (disposed || request !== groupRequest) return
      groups.value = response
    } catch (reason) {
      if (disposed || request !== groupRequest) return
      groups.value = []
      groupError.value = options.errorMessage(reason, `${options.label}品名分组加载失败，请稍后重试。`)
    } finally {
      if (!disposed && request === groupRequest) groupLoading.value = false
    }
  }

  function reset() {
    candidateRequest += 1
    groupRequest += 1
    loading.value = false
    groupLoading.value = false
    error.value = ''
    groupError.value = ''
    candidates.value = []
    groups.value = []
    total.value = 0
    page.value = 1
    materialName.value = ''
    keyword.value = ''
    groupKeyword.value = ''
    selected.value = {}
  }

  function open() {
    if (disposed) return
    reset()
    visible.value = true
    return Promise.all([loadGroups(), loadCandidates()])
  }
  function onClosed() {
    // 关闭动画结束时可能已经重开，不能清空新一轮选择。
    if (!visible.value) reset()
  }
  function search() { page.value = 1; return loadCandidates() }
  function changePage(value: number) { page.value = value; return loadCandidates() }
  function filterGroups(value: string) { groupKeyword.value = value }
  function clearGroupFilter(opened: boolean) { if (!opened) groupKeyword.value = '' }
  function toggleCandidate(item: BomHardwareMaterial, checked: boolean | string | number) {
    const next = { ...selected.value }
    if (Boolean(checked)) next[item.id] = item
    else delete next[item.id]
    selected.value = next
  }
  function toggleRow(item: BomHardwareMaterial) { toggleCandidate(item, !selected.value[item.id]) }
  function rowClass({ row }: { row: BomHardwareMaterial }) { return selected.value[row.id] ? 'is-picker-selected' : '' }
  function togglePage(checked: boolean | string | number) {
    const next = { ...selected.value }
    for (const item of candidates.value) {
      if (Boolean(checked)) next[item.id] = item
      else delete next[item.id]
    }
    selected.value = next
  }

  // 立即隔离关闭前的请求，不依赖窗口动画结束事件。
  watch(visible, opened => { if (!opened) reset() }, { flush: 'sync' })
  onScopeDispose(() => { disposed = true; reset() })

  return {
    label: options.label, visible, loading, error, groupLoading, groupError, groups, groupKeyword,
    materialName, keyword, page, pageSize, total, candidates, selected, visibleGroups, selectedCount,
    pageAllSelected, pageSelectionIndeterminate, loadCandidates, loadGroups, open, onClosed,
    search, changePage, filterGroups, clearGroupFilter, toggleCandidate, toggleRow, rowClass, togglePage,
  }
}
