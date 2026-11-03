<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Edit, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import ElDialog from '@/components/common/AppWindowDialog.vue'
import { fetchTubeFormula, fetchTubeFormulas, updateTubeFormula } from '@/api/tubeFormulas'
import type { TubeCalculationFormula, TubeFormulaGroup } from '@/types/tubeFormulas'

const props = defineProps<{ canEdit: boolean }>()
const groups: Array<{ key: TubeFormulaGroup; label: string; variables: string }> = [
  { key: 'ROUND', label: '圆管', variables: '直径、壁厚、管材长度' },
  { key: 'RECTANGULAR', label: '方管 / 矩形管', variables: '截面长、截面宽、壁厚、管材长度' },
  { key: 'OVAL', label: '椭圆管 / 扁圆管', variables: '截面长、截面宽、壁厚、管材长度' },
]
const records = ref<TubeCalculationFormula[]>([])
const loading = ref(false)
const loadError = ref('')
const openingId = ref('')
const editing = ref<TubeCalculationFormula | null>(null)
const dialogVisible = ref(false)
const saving = ref(false)
const saveError = ref('')
const etag = ref('')
const form = reactive({ area_expression: '', weight_expression: '' })
const editingGroup = computed(() => groups.find(group => group.key === editing.value?.group_key))

function errorMessage(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response?.data
  return Object.values(data?.error?.field_errors || {}).flat()[0] || data?.error?.message || data?.detail || fallback
}

function canClose(): boolean {
  if (saving.value || openingId.value) {
    ElMessage.warning('公式操作进行中，请稍候。')
    return false
  }
  if (dialogVisible.value) {
    ElMessage.warning('请先保存或取消当前公式编辑。')
    return false
  }
  return true
}
defineExpose({ canClose })

async function loadRecords() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetchTubeFormulas()
    if (groups.some(group => response.filter(row => row.group_key === group.key).length !== 1)) {
      records.value = []
      loadError.value = '管材公式配置不完整，请联系管理员检查三组公式配置。'
      return
    }
    records.value = groups.map(group => response.find(row => row.group_key === group.key)!)
  } catch (error) {
    records.value = []
    loadError.value = errorMessage(error, '计算公式加载失败，请重试。')
  } finally {
    loading.value = false
  }
}

async function openEdit(row: TubeCalculationFormula) {
  if (!props.canEdit || openingId.value || saving.value) return
  openingId.value = row.id
  saveError.value = ''
  try {
    const response = await fetchTubeFormula(row.id)
    if (!response.etag) {
      ElMessage.error('未取得公式版本，请刷新后重试。')
      return
    }
    editing.value = response.data
    etag.value = response.etag
    form.area_expression = response.data.area_expression
    form.weight_expression = response.data.weight_expression
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(errorMessage(error, '公式详情加载失败，请重试。'))
  } finally {
    openingId.value = ''
  }
}

async function save() {
  if (!props.canEdit || !editing.value || saving.value) return
  saveError.value = ''
  if (!form.area_expression.trim() || !form.weight_expression.trim()) {
    saveError.value = '喷塑面积公式和重量公式都不能为空。'
    return
  }
  saving.value = true
  try {
    const response = await updateTubeFormula(editing.value.id, {
      area_expression: form.area_expression.trim(), weight_expression: form.weight_expression.trim(),
    }, etag.value)
    records.value = records.value.map(row => row.id === response.data.id ? response.data : row)
    dialogVisible.value = false
    ElMessage.success('公式已保存，后续新计算使用新公式。')
  } catch (error) {
    const status = (error as { response?: { status?: number } })?.response?.status
    saveError.value = status === 412
      ? '公式已被其他人修改。本次输入已保留，请取消后重新编辑以获取最新版本。'
      : errorMessage(error, '公式保存失败，请检查后重试。')
  } finally {
    saving.value = false
  }
}

function beforeDialogClose(done: () => void) {
  if (!saving.value) done()
}

onMounted(loadRecords)
</script>

<template>
  <main class="tube-formulas" data-testid="tube-formula-settings">
    <div class="formula-heading erp-list-table-heading">
      <div><h2>计算公式</h2><span>单支管材 · 3 组公式</span></div>
      <el-button :icon="Refresh" :loading="loading" :disabled="!!openingId || dialogVisible" @click="loadRecords">刷新</el-button>
    </div>
    <p class="formula-hint">所有尺寸使用毫米（mm），管材长度取切割长度。喷塑面积单位为㎡，重量单位为 kg，公式不乘数量。</p>
    <p class="formula-hint">同组形状共用公式。保存后用于后续新计算，已有 BOM 不批量回算。</p>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
    <div v-loading="loading" class="formula-list">
      <section v-for="row in records" :key="row.id" class="formula-row" :data-group="row.group_key">
        <header>
          <h3>{{ groups.find(group => group.key === row.group_key)?.label }}</h3>
          <el-button v-if="canEdit" link :icon="Edit" :loading="openingId === row.id" :disabled="!!openingId || saving" @click="openEdit(row)">编辑</el-button>
        </header>
        <dl>
          <div><dt>喷塑单支面积（㎡）</dt><dd>{{ row.area_expression }}</dd></div>
          <div><dt>单支重量（kg）</dt><dd>{{ row.weight_expression }}</dd></div>
        </dl>
      </section>
      <el-empty v-if="!loading && !loadError && records.length === 0" description="暂无计算公式" />
    </div>
    <ElDialog v-model="dialogVisible" :title="`编辑${editingGroup?.label || ''}公式`" width="min(760px, 94vw)" destroy-on-close :close-on-click-modal="!saving" :close-on-press-escape="!saving" :before-close="beforeDialogClose" class="system-settings-dialog">
      <el-alert v-if="saveError" :title="saveError" type="error" :closable="false" show-icon class="formula-save-error" />
      <p class="formula-help">可用变量：{{ editingGroup?.variables }}（单位均为 mm）。支持数字、括号和加减乘除；乘除可使用 * / 或 × ÷。数量不参与单支计算。</p>
      <el-form label-position="top">
        <el-form-item label="喷塑单支面积公式（㎡）" required>
          <el-input v-model="form.area_expression" type="textarea" :rows="3" maxlength="500" show-word-limit :disabled="saving" aria-label="喷塑单支面积公式" />
        </el-form-item>
        <el-form-item label="单支重量公式（kg）" required>
          <el-input v-model="form.weight_expression" type="textarea" :rows="3" maxlength="500" show-word-limit :disabled="saving" aria-label="单支重量公式" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="saving" @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存公式</el-button>
      </template>
    </ElDialog>
  </main>
</template>

<style scoped>
.tube-formulas { display: flex; min-width: 0; min-height: 0; flex-direction: column; }
.formula-heading { display: flex; flex: none; align-items: center; justify-content: space-between; gap: 12px; }
.formula-heading > div { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; }
.formula-heading h2 { margin: 0; font-size: 14px; }
.formula-heading span, .formula-hint, .formula-help { color: var(--erp-color-text-secondary); font-size: 13px; line-height: 1.7; }
.formula-hint { margin: 0 0 8px; }
.formula-list { flex: 1; min-height: 0; overflow-y: auto; }
.formula-row { padding: 16px 0; border-bottom: 1px solid var(--erp-color-border); }
.formula-row:last-child { border-bottom: 0; }
.formula-row header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.formula-row h3 { margin: 0; font-size: 14px; }
.formula-row dl { display: grid; gap: 12px; margin: 12px 0 0; }
.formula-row dl > div { display: grid; grid-template-columns: 152px minmax(0, 1fr); gap: 12px; }
.formula-row dt { color: var(--erp-color-text-secondary); font-size: 13px; }
.formula-row dd { margin: 0; font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.formula-save-error { margin-bottom: 12px; }
.formula-help { margin: 0 0 16px; }
@media (max-width: 640px) { .formula-row dl > div { grid-template-columns: 1fr; gap: 4px; } }
</style>
