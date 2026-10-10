<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { createSampleOutbound, fetchSampleOutboundEligible } from '@/api/samples'
import { useAuthStore } from '@/stores/auth'
import type {
  SampleOutboundCreateLineInput,
  SampleOutboundCreated,
  SampleOutboundEligibleRow,
  SampleOutboundMethod,
} from '@/types/sample'

interface OutboundDialogRow extends SampleOutboundEligibleRow {
  checked: boolean
  inputQuantity: string
  inputMethod: SampleOutboundMethod | ''
  courierCompany: string
  trackingNumber: string
  remark: string
}

type InvalidField = 'quantity' | 'method' | 'courier' | 'detail'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [outbound: SampleOutboundCreated]
}>()

const authStore = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const rows = ref<OutboundDialogRow[]>([])
const loadState = ref<'ready' | 'empty' | 'error' | 'forbidden'>('ready')
const loadMessage = ref('')
const validationMessage = ref('')
const invalidFields = ref(new Map<string, Set<InvalidField>>())
const inventoryConflict = ref(false)
let eligibleRequest = 0
const canCreateOutbound = computed(() => authStore.hasPermission('samples.add_sampleinventoryoutbound'))
const controlsDisabled = computed(() => loading.value || submitting.value || !canCreateOutbound.value)

const methodOptions: Array<{ value: SampleOutboundMethod; label: string }> = [
  { value: 'MERCHANDISER_MAIL', label: '跟单员邮寄' },
  { value: 'SALESPERSON_CARRY', label: '业务员带走' },
  { value: 'OTHER', label: '其他' },
]

const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => { if (!submitting.value) emit('update:modelValue', value) },
})
const selectedRows = computed(() => rows.value.filter((row) => row.checked))
const selectedCount = computed(() => selectedRows.value.length)
const emptyText = computed(() => {
  if (loadState.value === 'forbidden') return loadMessage.value || '当前账号没有样品出库权限'
  if (loadState.value === 'error') return loadMessage.value || '可出库库存加载失败'
  return '暂无可出库样品'
})

function resetDialog() {
  rows.value = []
  loadState.value = 'ready'
  loadMessage.value = ''
  validationMessage.value = ''
  invalidFields.value = new Map()
  inventoryConflict.value = false
}

function getApiError(error: unknown): { status: number; message: string } {
  if (!(error instanceof AxiosError)) return { status: 0, message: '请求失败，请稍后重试。' }
  if (!error.response) return { status: 0, message: '网络连接异常，请检查后端服务后重试。' }
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  return {
    status: error.response.status,
    message: data?.error?.message || data?.detail || '请求失败，请稍后重试。',
  }
}

async function loadEligibleRows() {
  if (submitting.value) return
  const request = ++eligibleRequest
  if (!canCreateOutbound.value) {
    loadState.value = 'forbidden'
    loadMessage.value = '当前账号没有样品出库权限。'
    validationMessage.value = loadMessage.value
    loading.value = false
    return
  }
  loading.value = true
  loadMessage.value = ''
  invalidFields.value = new Map()
  try {
    const result = await fetchSampleOutboundEligible()
    if (request !== eligibleRequest || !props.modelValue) return
    const eligibleRows = new Map(result.data.map(row => [row.inventory_line_id, row]))
    for (let nextPage = 2; nextPage <= result.meta.total_pages; nextPage++) {
      const next = await fetchSampleOutboundEligible(nextPage)
      if (request !== eligibleRequest || !props.modelValue) return
      next.data.forEach(row => eligibleRows.set(row.inventory_line_id, row))
    }
    inventoryConflict.value = false
    rows.value = [...eligibleRows.values()].map((row) => ({
      ...row,
      checked: false,
      inputQuantity: '',
      inputMethod: '',
      courierCompany: '',
      trackingNumber: '',
      remark: '',
    }))
    loadState.value = rows.value.length ? 'ready' : 'empty'
    validationMessage.value = ''
  } catch (error) {
    if (request !== eligibleRequest || !props.modelValue) return
    const result = getApiError(error)
    rows.value = []
    loadState.value = result.status === 403 ? 'forbidden' : 'error'
    loadMessage.value = result.status === 401 ? '登录状态已失效，请重新登录。' : result.message
    validationMessage.value = loadMessage.value
    ElMessage.error(loadMessage.value)
  } finally {
    if (request === eligibleRequest) loading.value = false
  }
}

function handleSelectionChange() {
  validationMessage.value = ''
}

function clearFieldValidation(row: OutboundDialogRow, ...fields: InvalidField[]) {
  const next = new Map(invalidFields.value)
  const rowFields = new Set(next.get(row.inventory_line_id) || [])
  fields.forEach((field) => rowFields.delete(field))
  if (rowFields.size) next.set(row.inventory_line_id, rowFields)
  else next.delete(row.inventory_line_id)
  invalidFields.value = next
}

function isInvalid(row: OutboundDialogRow, field: InvalidField): boolean {
  return invalidFields.value.get(row.inventory_line_id)?.has(field) ?? false
}

function handleMethodChange(row: OutboundDialogRow) {
  if (row.inputMethod === 'MERCHANDISER_MAIL') {
    row.remark = ''
  } else if (row.inputMethod === 'SALESPERSON_CARRY') {
    row.courierCompany = ''
    row.trackingNumber = ''
    row.remark = ''
  } else if (row.inputMethod === 'OTHER') {
    row.courierCompany = ''
    row.trackingNumber = ''
  }
  clearFieldValidation(row, 'method', 'courier', 'detail')
}

function productDescription(row: OutboundDialogRow): string {
  return [row.product_name, row.specification, row.color].filter(Boolean).join(' / ') || '—'
}

function validateRows(): SampleOutboundCreateLineInput[] | null {
  if (!selectedRows.value.length) {
    validationMessage.value = '未选择任何数据，请至少选择一条库存明细。'
    return null
  }
  if (selectedRows.value.length > 100) {
    validationMessage.value = '一次最多提交 100 条库存明细，请分批出库。'
    return null
  }

  const nextInvalid = new Map<string, Set<InvalidField>>()
  const messages: string[] = []
  const payload: SampleOutboundCreateLineInput[] = []

  selectedRows.value.forEach((row, index) => {
    const rowNumber = index + 1
    const rowErrors = new Set<InvalidField>()
    const quantity = Number(row.inputQuantity)
    if (!Number.isSafeInteger(quantity) || quantity <= 0) {
      rowErrors.add('quantity')
      messages.push(`第 ${rowNumber} 行出库数量须为正整数`)
    } else if (quantity > row.available_quantity) {
      rowErrors.add('quantity')
      messages.push(`第 ${rowNumber} 行数量超过可用库存 ${row.available_quantity}`)
    }
    if (!methodOptions.some(option => option.value === row.inputMethod)) {
      rowErrors.add('method')
      messages.push(`第 ${rowNumber} 行请选择出库方式`)
    } else if (row.inputMethod === 'MERCHANDISER_MAIL') {
      if (!row.courierCompany.trim()) {
        rowErrors.add('courier')
        messages.push(`第 ${rowNumber} 行邮寄需填写快递公司`)
      }
      if (!row.trackingNumber.trim()) {
        rowErrors.add('detail')
        messages.push(`第 ${rowNumber} 行邮寄需填写快递单号`)
      }
    } else if (row.inputMethod === 'OTHER' && !row.remark.trim()) {
      rowErrors.add('detail')
      messages.push(`第 ${rowNumber} 行其他方式需填写备注`)
    }
    if (rowErrors.size) nextInvalid.set(row.inventory_line_id, rowErrors)

    if (
      rowErrors.size === 0
      && row.inputMethod
      && Number.isSafeInteger(quantity)
      && quantity > 0
      && quantity <= row.available_quantity
    ) {
      payload.push({
        inventory_line_id: row.inventory_line_id,
        outbound_quantity: quantity,
        outbound_method: row.inputMethod,
        courier_company: row.inputMethod === 'MERCHANDISER_MAIL' ? row.courierCompany.trim() : '',
        tracking_number: row.inputMethod === 'MERCHANDISER_MAIL' ? row.trackingNumber.trim() : '',
        remark: row.inputMethod === 'OTHER' ? row.remark.trim() : '',
        expected_available_quantity: row.available_quantity,
      })
    }
  })

  invalidFields.value = nextInvalid
  if (messages.length) {
    validationMessage.value = `校验：${messages.join('；')}。`
    return null
  }
  validationMessage.value = '校验通过，可以提交出库。'
  return payload
}

async function submitOutbound() {
  if (controlsDisabled.value || inventoryConflict.value || loadState.value !== 'ready') return
  const items = validateRows()
  if (!items) {
    ElMessage.warning(validationMessage.value)
    return
  }

  submitting.value = true
  try {
    const outbound = await createSampleOutbound(items)
    ElMessage.success(`出库成功，单号：${outbound.outbound_number}`)
    emit('created', outbound)
    emit('update:modelValue', false)
  } catch (error) {
    const result = getApiError(error)
    if (result.status === 409) {
      inventoryConflict.value = true
      validationMessage.value = '库存已变化，请刷新可选样品后重新提交。'
    }
    else if (result.status === 403) validationMessage.value = '当前账号没有样品出库权限。'
    else if (result.status === 401) validationMessage.value = '登录状态已失效，请重新登录。'
    else validationMessage.value = result.message
    ElMessage.error(validationMessage.value)
  } finally {
    submitting.value = false
  }
}

function closeDialog() {
  if (!submitting.value) dialogVisible.value = false
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      resetDialog()
      void loadEligibleRows()
    } else {
      eligibleRequest++
      loading.value = false
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => { eligibleRequest++ })
</script>

<template>
  <ElDialog
    v-model="dialogVisible"
    title="批量出库样品"
    class="sample-batch-dialog sample-outbound-create-dialog" modal-class="sample-outbound-overlay" data-figma-node="814:9235"
    width="min(1500px, calc(100vw - 32px))"
    :height="480"
    align-center
    draggable
    overflow
    append-to-body
    destroy-on-close
    :show-close="!submitting"
    :close-on-click-modal="false"
    :close-on-press-escape="!submitting"
  >
    <div class="outbound-dialog-content">
      <section class="outbound-detail-panel batch-detail-panel" aria-label="可出库库存明细">
        <ElTable
          v-loading="loading"
          :data="rows"
          row-key="inventory_line_id"
          height="350"
          :empty-text="emptyText"
        >
          <ElTableColumn label="选择" width="56" fixed="left" align="center">
            <template #default="{ row }">
              <ElCheckbox
                v-model="row.checked"
                :aria-label="`选择 ${row.receipt_number}`"
                :disabled="controlsDisabled"
                @change="handleSelectionChange"
              />
            </template>
          </ElTableColumn>
          <ElTableColumn prop="receipt_number" label="来源入库批次" width="156" show-overflow-tooltip />
          <ElTableColumn label="产品名称 / 规格 / 颜色" min-width="250" show-overflow-tooltip>
            <template #default="{ row }">{{ productDescription(row) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="available_quantity" label="可用" width="64" align="center" />
          <ElTableColumn label="出库数量 *" width="108">
            <template #default="{ row }">
              <ElInput
                v-model="row.inputQuantity"
                class="line-input quantity-input" :aria-label="`${row.receipt_number} 出库数量`"
                :class="{ 'is-invalid': isInvalid(row, 'quantity') }"
                type="number"
                min="1"
                :max="row.available_quantity"
                inputmode="numeric"
                placeholder="数量"
                :disabled="!row.checked || controlsDisabled"
                @input="clearFieldValidation(row, 'quantity')"
              />
            </template>
          </ElTableColumn>
          <ElTableColumn label="出库方式 *" width="136">
            <template #default="{ row }">
              <ElSelect
                v-model="row.inputMethod"
                class="line-select method-select" :aria-label="`${row.receipt_number} 出库方式`"
                :class="{ 'is-invalid': isInvalid(row, 'method') }"
                placeholder="选择方式"
                :disabled="!row.checked || controlsDisabled"
                @change="handleMethodChange(row)"
              >
                <ElOption
                  v-for="option in methodOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
            </template>
          </ElTableColumn>
          <ElTableColumn label="快递公司" width="126">
            <template #default="{ row }">
              <ElInput
                v-if="row.inputMethod === 'MERCHANDISER_MAIL'"
                v-model="row.courierCompany"
                class="line-input courier-input" :aria-label="`${row.receipt_number} 快递公司`"
                :class="{ 'is-invalid': isInvalid(row, 'courier') }"
                maxlength="150"
                placeholder="快递公司"
                :disabled="!row.checked || controlsDisabled"
                @input="clearFieldValidation(row, 'courier')"
              />
              <span v-else class="hidden-field">—（隐藏）</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="快递单号 / 备注" width="220">
            <template #default="{ row }">
              <ElInput
                v-if="row.inputMethod === 'MERCHANDISER_MAIL'"
                v-model="row.trackingNumber"
                class="line-input delivery-input" :aria-label="`${row.receipt_number} 快递单号`"
                :class="{ 'is-invalid': isInvalid(row, 'detail') }"
                maxlength="150"
                placeholder="快递单号"
                :disabled="!row.checked || controlsDisabled"
                @input="clearFieldValidation(row, 'detail')"
              />
              <ElInput
                v-else-if="row.inputMethod === 'OTHER'"
                v-model="row.remark"
                class="line-input remark-input" :aria-label="`${row.receipt_number} 其他原因`"
                :class="{ 'is-invalid': isInvalid(row, 'detail') }"
                maxlength="500"
                placeholder="请输入其他原因"
                :disabled="!row.checked || controlsDisabled"
                @input="clearFieldValidation(row, 'detail')"
              />
              <span v-else class="hidden-field">—（隐藏）</span>
            </template>
          </ElTableColumn>
        </ElTable>

      </section>
    </div>

    <template #footer>
      <div class="outbound-dialog-footer batch-dialog-footer">
        <div class="footer-status">
          <span>已选择 {{ selectedCount }} 条</span>
          <ElButton
            v-if="loadState === 'error' || loadState === 'forbidden' || inventoryConflict"
            link
            type="primary"
            :icon="Refresh"
            :loading="loading"
            :disabled="submitting || !canCreateOutbound"
            @click="loadEligibleRows"
          >重新加载</ElButton>
        </div>
        <div class="footer-actions">
          <ElButton :disabled="submitting" @click="closeDialog">取消</ElButton>
          <ElButton
            type="primary"
            :loading="submitting"
            :disabled="controlsDisabled || inventoryConflict || loadState !== 'ready'"
            @click="submitOutbound"
          >确认出库</ElButton>
        </div>
      </div>
    </template>
  </ElDialog>
</template>

<style lang="scss" src="./sampleOutboundCreateDialog.scss"></style>
