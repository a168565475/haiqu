<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { createSampleLoan, fetchSampleLoanEligible } from '@/api/samples'
import { useAuthStore } from '@/stores/auth'
import type {
  SampleLoanCreateLineInput,
  SampleLoanCreated,
  SampleLoanEligibleRow,
} from '@/types/sample'

interface LoanDialogRow extends SampleLoanEligibleRow {
  checked: boolean
  inputQuantity: string
  borrowerName: string
  purposeNote: string
}

type InvalidField = 'quantity' | 'borrower' | 'purpose'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [loan: SampleLoanCreated]
}>()

const authStore = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const rows = ref<LoanDialogRow[]>([])
const loadState = ref<'ready' | 'empty' | 'error' | 'forbidden'>('ready')
const loadMessage = ref('')
const validationMessage = ref('')
const invalidFields = ref(new Map<string, Set<InvalidField>>())
const inventoryConflict = ref(false)
let eligibleRequest = 0
const canCreateLoan = computed(() => authStore.hasPermission('samples.add_sampleinventoryloan'))
const controlsDisabled = computed(() => loading.value || submitting.value || !canCreateLoan.value)

const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => { if (!submitting.value) emit('update:modelValue', value) },
})
const selectedRows = computed(() => rows.value.filter((row) => row.checked))
const selectedCount = computed(() => selectedRows.value.length)
const emptyText = computed(() => {
  if (loadState.value === 'forbidden') return loadMessage.value || '当前账号没有样品借出权限'
  if (loadState.value === 'error') return loadMessage.value || '可借出库存加载失败'
  return '暂无可借出样品'
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
  if (!canCreateLoan.value) {
    loadState.value = 'forbidden'
    loadMessage.value = '当前账号没有样品借出权限。'
    validationMessage.value = loadMessage.value
    loading.value = false
    return
  }
  loading.value = true
  loadMessage.value = ''
  invalidFields.value = new Map()
  try {
    const result = await fetchSampleLoanEligible()
    if (request !== eligibleRequest || !props.modelValue) return
    const eligibleRows = new Map(result.data.map(row => [row.inventory_line_id, row]))
    for (let nextPage = 2; nextPage <= result.meta.total_pages; nextPage++) {
      const next = await fetchSampleLoanEligible(nextPage)
      if (request !== eligibleRequest || !props.modelValue) return
      next.data.forEach(row => eligibleRows.set(row.inventory_line_id, row))
    }
    inventoryConflict.value = false
    rows.value = [...eligibleRows.values()].map((row) => ({
      ...row,
      checked: false,
      inputQuantity: '',
      borrowerName: '',
      purposeNote: '',
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

function clearFieldValidation(row: LoanDialogRow, ...fields: InvalidField[]) {
  const next = new Map(invalidFields.value)
  const rowFields = new Set(next.get(row.inventory_line_id) || [])
  fields.forEach((field) => rowFields.delete(field))
  if (rowFields.size) next.set(row.inventory_line_id, rowFields)
  else next.delete(row.inventory_line_id)
  invalidFields.value = next
}

function isInvalid(row: LoanDialogRow, field: InvalidField): boolean {
  return invalidFields.value.get(row.inventory_line_id)?.has(field) ?? false
}

function productDescription(row: LoanDialogRow): string {
  return [row.product_name, row.specification, row.color].filter(Boolean).join(' / ') || '—'
}

function validateRows(): SampleLoanCreateLineInput[] | null {
  if (!selectedRows.value.length) {
    validationMessage.value = '未选择任何数据，请至少选择一条库存明细。'
    return null
  }
  if (selectedRows.value.length > 100) {
    validationMessage.value = '一次最多提交 100 条库存明细，请分批借出。'
    return null
  }

  const nextInvalid = new Map<string, Set<InvalidField>>()
  const messages: string[] = []
  const payload: SampleLoanCreateLineInput[] = []

  selectedRows.value.forEach((row, index) => {
    const rowNumber = index + 1
    const rowErrors = new Set<InvalidField>()
    const quantity = Number(row.inputQuantity)
    if (!Number.isSafeInteger(quantity) || quantity <= 0) {
      rowErrors.add('quantity')
      messages.push(`第 ${rowNumber} 行借出数量须为正整数`)
    } else if (quantity > row.available_quantity) {
      rowErrors.add('quantity')
      messages.push(`第 ${rowNumber} 行数量超过可用库存 ${row.available_quantity}`)
    }
    if (!row.borrowerName.trim()) {
      rowErrors.add('borrower')
      messages.push(`第 ${rowNumber} 行借用人必填`)
    }
    if (!row.purposeNote.trim()) {
      rowErrors.add('purpose')
      messages.push(`第 ${rowNumber} 行用途或备注必填`)
    }
    if (rowErrors.size) nextInvalid.set(row.inventory_line_id, rowErrors)

    if (
      rowErrors.size === 0
      && Number.isSafeInteger(quantity)
      && quantity > 0
      && quantity <= row.available_quantity
    ) {
      payload.push({
        inventory_line_id: row.inventory_line_id,
        loan_quantity: quantity,
        borrower_name: row.borrowerName.trim(),
        purpose_note: row.purposeNote.trim(),
        expected_available_quantity: row.available_quantity,
      })
    }
  })

  invalidFields.value = nextInvalid
  if (messages.length) {
    validationMessage.value = `校验：${messages.join('；')}。`
    return null
  }
  validationMessage.value = '校验通过，可以提交借出。'
  return payload
}

async function submitLoan() {
  if (controlsDisabled.value || inventoryConflict.value || loadState.value !== 'ready') return
  const items = validateRows()
  if (!items) {
    ElMessage.warning(validationMessage.value)
    return
  }

  submitting.value = true
  try {
    const loan = await createSampleLoan(items)
    ElMessage.success(`借出成功，单号：${loan.loan_number}`)
    emit('created', loan)
    emit('update:modelValue', false)
  } catch (error) {
    const result = getApiError(error)
    if (result.status === 409) {
      inventoryConflict.value = true
      validationMessage.value = '库存已变化，请刷新可选样品后重新提交。'
    }
    else if (result.status === 403) validationMessage.value = '当前账号没有样品借出权限。'
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
    title="批量借出样品"
    class="sample-batch-dialog sample-loan-create-dialog" modal-class="sample-loan-overlay" data-figma-node="814:9529"
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
    <div class="loan-dialog-content">
      <section class="loan-detail-panel batch-detail-panel" aria-label="可借出库存明细">
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
          <ElTableColumn label="产品名称 / 规格 / 颜色" min-width="270" show-overflow-tooltip>
            <template #default="{ row }">{{ productDescription(row) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="available_quantity" label="可用" width="64" align="center" />
          <ElTableColumn label="借出数量 *" width="112">
            <template #default="{ row }">
              <ElInput
                v-model="row.inputQuantity"
                class="line-input quantity-input" :aria-label="`${row.receipt_number} 借出数量`"
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
          <ElTableColumn label="借用人 *" width="150">
            <template #default="{ row }">
              <ElInput
                v-model="row.borrowerName"
                class="line-input borrower-input" :aria-label="`${row.receipt_number} 借用人`"
                :class="{ 'is-invalid': isInvalid(row, 'borrower') }"
                maxlength="150"
                placeholder="请输入借用人"
                :disabled="!row.checked || controlsDisabled"
                @input="clearFieldValidation(row, 'borrower')"
              />
            </template>
          </ElTableColumn>
          <ElTableColumn label="用途 / 备注 *" width="310">
            <template #default="{ row }">
              <ElInput
                v-model="row.purposeNote"
                class="line-input purpose-input" :aria-label="`${row.receipt_number} 用途备注`"
                :class="{ 'is-invalid': isInvalid(row, 'purpose') }"
                maxlength="500"
                placeholder="请输入用途或备注"
                :disabled="!row.checked || controlsDisabled"
                @input="clearFieldValidation(row, 'purpose')"
              />
            </template>
          </ElTableColumn>
        </ElTable>

      </section>
    </div>

    <template #footer>
      <div class="loan-dialog-footer batch-dialog-footer">
        <div class="footer-status">
          <span>已选择 {{ selectedCount }} 条</span>
          <ElButton
            v-if="loadState === 'error' || loadState === 'forbidden' || inventoryConflict"
            link
            type="primary"
            :icon="Refresh"
            :loading="loading"
            :disabled="submitting || !canCreateLoan"
            @click="loadEligibleRows"
          >重新加载</ElButton>
        </div>
        <div class="footer-actions">
          <ElButton :disabled="submitting" @click="closeDialog">取消</ElButton>
          <ElButton
            type="primary"
            :loading="submitting"
            :disabled="controlsDisabled || inventoryConflict || loadState !== 'ready'"
            @click="submitLoan"
          >确认借出</ElButton>
        </div>
      </div>
    </template>
  </ElDialog>
</template>

<style lang="scss" src="./sampleLoanCreateDialog.scss"></style>
