<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ElDialog from '@/components/common/AppWindowDialog.vue'
import {
  changePublicMaterialRecordStatus, createPublicMaterialRecord, fetchPublicMaterialFields,
  fetchPublicMaterialRecord, fetchPublicMaterialRecords, fetchPublicTubeOptions, materialCatalogError,
  materialCatalogErrorStatus, updatePublicMaterialRecord,
} from '@/api/materialCatalog'
import { useAuthStore } from '@/stores/auth'
import type {
  MaterialScope, PublicMaterialFields, PublicMaterialRecord, PublicMaterialRecordInput,
  PublicMaterialRecordsQuery, PublicMaterialResource, PublicTubeOptions,
} from '@/types/materialCatalog'
import type { ReferenceStatus } from '@/types/referenceData'

const props = defineProps<{
  categoryKey: string
  templateKey: string
  scope: MaterialScope
  fieldKey: string
}>()
const emit = defineEmits<{ 'open-existing': [resource: string] }>()
const authStore = useAuthStore()
const can = (permission: string) => authStore.user?.is_superuser === true || authStore.hasPermission(permission)
const canView = computed(() => can('material_catalog.view_materialcatalog'))
const canMaintain = computed(() => can('material_catalog.change_materialcatalog') || (canView.value && can('products.add_rawmaterialinformation')))
const canChangeStatus = computed(() => can('material_catalog.change_materialcatalog'))
const metadata = ref<PublicMaterialFields>({ categories: [], spray_fields: [] })
const metadataLoading = ref(false)
const metadataError = ref('')
const categoryKey = ref('')
const templateKey = ref('')
const scope = ref<MaterialScope>('BASE')
const fieldKey = ref('')
const category = computed(() => metadata.value.categories.find(item => item.key === categoryKey.value))
const template = computed(() => category.value?.templates.find(item => item.key === templateKey.value))
const fields = computed(() => scope.value === 'SPRAY'
  ? (template.value?.supports_spray ? metadata.value.spray_fields : []) : template.value?.fields || [])
const field = computed(() => fields.value.find(item => item.key === fieldKey.value))
const resource = computed<PublicMaterialResource | null>(() => {
  const source = field.value?.source
  return source === 'material-attribute-values' || source === 'tube-shape-dimensions' ? source : null
})
const isDimension = computed(() => resource.value === 'tube-shape-dimensions')
const isAggregatedWeight = computed(() => categoryKey.value === 'AUXILIARY' && templateKey.value === 'COTTON' && scope.value === 'BASE' && fieldKey.value === 'gram_weight')
const records = ref<PublicMaterialRecord[]>([])
const loading = ref(false)
const loadError = ref('')
const keyword = ref('')
const statusFilter = ref<ReferenceStatus | ''>('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
let requestId = 0
let mounted = true
const dialogVisible = ref(false)
const editing = ref<PublicMaterialRecord | null>(null)
const currentEtag = ref('')
const saving = ref(false)
const opening = ref(false)
const statusBusy = ref(false)
const busy = computed(() => saving.value || opening.value || statusBusy.value)
const saveError = ref('')
const shapes = ref<PublicTubeOptions['shapes']>([])
const diameters = ref<PublicTubeOptions['diameters']>([])
const form = reactive({ value: '', shape: '', diameter: '', sort_order: 0, description: '' })

function canClose(): boolean {
  if (busy.value) {
    ElMessage.warning('原料属性操作进行中，请稍候。')
    return false
  }
  if (dialogVisible.value) {
    ElMessage.warning('请先保存或取消当前原料属性编辑。')
    return false
  }
  return true
}
defineExpose({ canClose })
onBeforeRouteLeave(canClose)
onBeforeRouteUpdate(canClose)

async function applyParentSelection() {
  if (!metadata.value.categories.length || !canClose()) return
  // 父页先调用 canClose；这里仍保留当前已接受的上下文，防止外部误切覆盖打开的编辑稿。
  categoryKey.value = props.categoryKey
  templateKey.value = props.templateKey
  scope.value = props.scope
  fieldKey.value = props.fieldKey
  keyword.value = ''
  statusFilter.value = ''
  page.value = 1
  await loadRecords()
}
function isSpecificationSource(row: PublicMaterialRecord) {
  return 'source_kind' in row && row.source_kind === 'SPECIFICATION'
}
function recordEditable(row: PublicMaterialRecord) {
  return !isSpecificationSource(row) && (!('editable' in row) || row.editable !== false)
}
function openSourceSpecifications() {
  if (canClose()) emit('open-existing', 'accessory-specifications')
}

async function loadMetadata() {
  if (metadataLoading.value || !canClose()) return
  metadataLoading.value = true
  metadataError.value = ''
  try {
    const response = await fetchPublicMaterialFields()
    if (!mounted) return
    metadata.value = response
    await applyParentSelection()
  } catch (error) {
    if (mounted) metadataError.value = materialCatalogError(error)
  } finally {
    if (mounted) metadataLoading.value = false
  }
}

async function loadRecords() {
  const current = ++requestId
  records.value = []
  total.value = 0
  loadError.value = ''
  const requestedResource = resource.value
  if (!requestedResource || !canView.value) {
    loading.value = false
    return
  }
  const query: PublicMaterialRecordsQuery = {
    q: keyword.value.trim() || undefined,
    status: statusFilter.value || undefined,
    page: page.value,
    page_size: pageSize.value,
  }
  if (requestedResource === 'material-attribute-values') {
    Object.assign(query, { category_key: categoryKey.value, template_key: templateKey.value, scope: scope.value, field_key: fieldKey.value })
  }
  loading.value = true
  try {
    const response = await fetchPublicMaterialRecords(requestedResource, query)
    if (!mounted || current !== requestId) return
    records.value = response.data
    total.value = response.meta.total
  } catch (error) {
    if (mounted && current === requestId) loadError.value = materialCatalogError(error)
  } finally {
    if (mounted && current === requestId) loading.value = false
  }
}

function search() {
  if (!canClose()) return
  page.value = 1
  void loadRecords()
}
function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  search()
}

async function openCreate() {
  if (!resource.value || !canMaintain.value || !canClose()) return
  editing.value = null
  currentEtag.value = ''
  saveError.value = ''
  Object.assign(form, { value: '', shape: '', diameter: '', sort_order: 0, description: '' })
  opening.value = true
  try {
    if (isDimension.value) {
      const options = await fetchPublicTubeOptions()
      if (!mounted) return
      shapes.value = options.shapes
      diameters.value = options.diameters
    }
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(materialCatalogError(error))
  } finally {
    opening.value = false
  }
}

async function openEdit(row: PublicMaterialRecord) {
  const selectedResource = resource.value
  if (!selectedResource || !recordEditable(row) || !canMaintain.value || !canClose()) return
  opening.value = true
  saveError.value = ''
  try {
    const response = await fetchPublicMaterialRecord(selectedResource, row.id)
    if (!mounted) return
    if (!response.etag) {
      ElMessage.error('未取得配置版本，请刷新后重试。')
      return
    }
    editing.value = response.data
    currentEtag.value = response.etag
    Object.assign(form, {
      value: 'value' in response.data ? response.data.value : '',
      shape: 'shape' in response.data ? response.data.shape : '',
      diameter: 'diameter' in response.data ? response.data.diameter : '',
      sort_order: response.data.sort_order,
      description: response.data.description,
    })
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(materialCatalogError(error))
  } finally {
    opening.value = false
  }
}

async function save() {
  const selectedResource = resource.value
  if (!selectedResource || !canMaintain.value || saving.value) return
  saveError.value = ''
  if (isDimension.value ? !form.shape || !form.diameter : !form.value.trim()) {
    saveError.value = isDimension.value ? '请选择形状和规格。' : `请填写${field.value?.label || '属性值'}。`
    return
  }
  if (!Number.isInteger(form.sort_order) || form.sort_order < 0) {
    saveError.value = '排序须为零或正整数。'
    return
  }
  saving.value = true
  try {
    const common = { sort_order: form.sort_order, description: form.description.trim() }
    if (editing.value) {
      await updatePublicMaterialRecord(selectedResource, editing.value.id, {
        ...common, ...(!isDimension.value ? { value: form.value.trim() } : {}),
      }, currentEtag.value)
    } else {
      const payload: PublicMaterialRecordInput = isDimension.value
        ? { ...common, shape: form.shape, diameter: form.diameter }
        : { ...common, category_key: categoryKey.value, template_key: templateKey.value, scope: scope.value, field_key: fieldKey.value, value: form.value.trim() }
      await createPublicMaterialRecord(selectedResource, payload)
    }
    dialogVisible.value = false
    ElMessage.success('公共配置已保存。')
    await loadRecords()
  } catch (error) {
    const status = materialCatalogErrorStatus(error)
    saveError.value = status === 412 || status === 428
      ? '配置版本已变化，本次输入已保留。请取消后重新编辑，核对最新配置再保存。'
      : materialCatalogError(error)
  } finally {
    saving.value = false
  }
}

async function changeStatus(row: PublicMaterialRecord) {
  const selectedResource = resource.value
  if (!selectedResource || !recordEditable(row) || !canChangeStatus.value || !canClose()) return
  const action = row.status === 'ACTIVE' ? 'deactivate' : 'activate'
  const label = action === 'deactivate' ? '停用' : '启用'
  statusBusy.value = true
  try {
    const detail = await fetchPublicMaterialRecord(selectedResource, row.id)
    if (!detail.etag) {
      ElMessage.error('未取得配置版本，请刷新后重试。')
      return
    }
    const answer = await ElMessageBox.prompt(`请输入${label}原因`, `${label}${field.value?.label || '公共配置'}`, {
      inputValidator: value => Boolean(value?.trim()) || '原因不能为空',
      confirmButtonText: `确认${label}`,
    })
    await changePublicMaterialRecordStatus(selectedResource, row.id, action, detail.etag, answer.value.trim())
    ElMessage.success(`${label}成功。`)
    await loadRecords()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(materialCatalogError(error))
  } finally {
    statusBusy.value = false
  }
}

function beforeDialogClose(done: () => void) { if (!saving.value) done() }
watch(() => [props.categoryKey, props.templateKey, props.scope, props.fieldKey], applyParentSelection)
onMounted(loadMetadata)
onBeforeUnmount(() => { mounted = false; requestId++ })
</script>

<template>
  <section v-loading="metadataLoading" class="public-material-settings" data-testid="public-material-options-settings">
    <div v-if="metadataError" class="data-card erp-list-data public-metadata-error">
      <el-alert :title="metadataError" type="error" :closable="false" show-icon />
      <el-button :icon="Refresh" @click="loadMetadata">重新加载</el-button>
    </div>
    <template v-else>
      <main class="data-card erp-list-data public-options-main">
        <template v-if="field && resource && canView">
          <div class="public-options-heading erp-list-toolbar">
            <div><h2>{{ field.label }}</h2><span>共 {{ total }} 条</span></div>
            <div>
              <el-button :icon="Refresh" :disabled="busy || dialogVisible" @click="loadRecords">刷新</el-button>
              <el-button v-if="canMaintain" type="primary" :icon="Plus" :loading="opening" :disabled="busy || dialogVisible" @click="openCreate">新增{{ isDimension ? '形状规格' : field.label }}</el-button>
            </div>
          </div>
          <p class="public-options-hint">{{ isDimension ? '将已有规格关联到形状，选料时按形状显示规格。' : isAggregatedWeight ? '克重合并已有辅料规格和公共配置；来源规格项只读，请在本组规格中修改。' : '此处维护公共选项，供原料属性和选料时使用。' }}</p>
          <div class="public-options-filters erp-list-filters">
            <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索当前属性" :disabled="busy || dialogVisible" @keyup.enter="search" />
            <el-select v-model="statusFilter" clearable placeholder="全部状态" :disabled="busy || dialogVisible">
              <el-option label="启用" value="ACTIVE" /><el-option label="停用" value="INACTIVE" />
            </el-select>
            <el-button :disabled="busy || dialogVisible" @click="resetFilters">重置</el-button>
            <el-button type="primary" :disabled="busy || dialogVisible" @click="search">应用筛选</el-button>
          </div>
          <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
          <div class="erp-list-table-frame">
            <el-table v-loading="loading" :data="records" height="100%" row-key="id">
              <template v-if="isDimension"><el-table-column prop="shape_name" label="形状" min-width="130" /><el-table-column prop="diameter_value" label="规格" min-width="160" /></template>
              <el-table-column v-else prop="value" :label="field.label" min-width="180" show-overflow-tooltip />
              <el-table-column v-if="isAggregatedWeight" label="来源" width="110"><template #default="row">{{ isSpecificationSource(row.row) ? '辅料规格' : '公共配置' }}</template></el-table-column>
              <el-table-column v-if="isAggregatedWeight" label="使用规格数" width="110"><template #default="row">{{ row.row.source_count ?? 0 }}</template></el-table-column>
              <el-table-column label="状态" width="90"><template #default="row"><el-tag :type="row.row.status === 'ACTIVE' ? 'success' : 'info'" effect="light">{{ row.row.status === 'ACTIVE' ? '启用' : '停用' }}</el-tag></template></el-table-column>
              <el-table-column prop="sort_order" label="排序" width="82" />
              <el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip />
              <el-table-column v-if="canMaintain || canChangeStatus || isAggregatedWeight" label="操作" width="150" fixed="right">
                <template #default="row">
                  <el-button v-if="isSpecificationSource(row.row)" link :disabled="busy || dialogVisible" @click="openSourceSpecifications">维护来源规格</el-button>
                  <template v-else-if="recordEditable(row.row)">
                    <el-button v-if="canMaintain" link :icon="Edit" :disabled="busy || dialogVisible" @click="openEdit(row.row)">编辑</el-button>
                    <el-button v-if="canChangeStatus" link :disabled="busy || dialogVisible" @click="changeStatus(row.row)">{{ row.row.status === 'ACTIVE' ? '停用' : '启用' }}</el-button>
                  </template>
                </template>
              </el-table-column>
              <template #empty><el-empty :description="loadError ? '加载失败，请重试' : '暂无公共选项'" /></template>
            </el-table>
          </div>
          <footer v-if="total > pageSize" class="erp-list-footer"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" :disabled="busy || dialogVisible" layout="total, sizes, prev, pager, next" @current-change="loadRecords" @size-change="page = 1; loadRecords()" /></footer>
        </template>
        <el-empty v-else :description="!field ? '当前属性配置不存在，请刷新生产维护' : !resource ? '当前属性由已有维护表管理' : '当前账号没有公共原料属性的查看权限'" />
      </main>
    </template>
    <ElDialog v-model="dialogVisible" :title="`${editing ? '编辑' : '新增'}${isDimension ? '形状规格' : field?.label || '属性'}`" width="min(600px, 94vw)" destroy-on-close :close-on-click-modal="!saving" :close-on-press-escape="!saving" :before-close="beforeDialogClose" class="system-settings-dialog">
      <el-alert v-if="saveError" :title="saveError" type="error" :closable="false" show-icon class="public-save-error" />
      <el-form label-position="top" :disabled="saving">
        <template v-if="isDimension">
          <el-form-item label="形状" required>
            <el-input v-if="editing && 'shape_name' in editing" :model-value="editing.shape_name" disabled />
            <el-select v-else v-model="form.shape" filterable placeholder="选择已有形状"><el-option v-for="item in shapes" :key="item.id" :label="item.shape_name" :value="item.id" /></el-select>
          </el-form-item>
          <el-form-item label="规格" required>
            <el-input v-if="editing && 'diameter_value' in editing" :model-value="editing.diameter_value" disabled />
            <el-select v-else v-model="form.diameter" filterable placeholder="选择已有规格"><el-option v-for="item in diameters" :key="item.id" :label="item.diameter_value" :value="item.id" /></el-select>
          </el-form-item>
          <p class="public-options-hint">{{ editing ? '形状和规格对应关系固定；需要调整时，请停用旧关系并新增。' : '缺少选项时，请先取消，在管材分组维护形状或规格，再新增关联。' }}</p>
        </template>
        <el-form-item v-else :label="field?.label || '属性值'" required><el-input v-model="form.value" maxlength="300" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" :precision="0" controls-position="right" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="2" maxlength="500" /></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </ElDialog>
  </section>
</template>

<style scoped>
.public-material-settings { display: grid; min-width: 0; min-height: 0; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); }
.public-metadata-error { grid-column: 1 / -1; gap: 12px; align-items: flex-start; }
.public-options-main { min-width: 0; min-height: 0; }
.public-options-heading, .public-options-heading > div { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.public-options-heading { flex: none; justify-content: space-between; }
.public-options-heading h2 { margin: 0; font-size: 14px; }
.public-options-heading span, .public-options-hint { color: var(--erp-color-text-secondary); font-size: 13px; line-height: 1.6; }
.public-options-hint { margin: 8px 0; }
.public-options-filters { display: flex; flex: none; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px; }
.public-options-filters > .el-input { width: min(280px, 100%); }
.public-options-filters > .el-select { width: 130px; }
.public-save-error { margin-bottom: 12px; }
.el-form :deep(.el-select) { width: 100%; }
</style>
