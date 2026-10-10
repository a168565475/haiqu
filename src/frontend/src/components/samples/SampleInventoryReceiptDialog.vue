<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  createSampleInventoryReceipt,
  fetchSampleFinishedGoodsOptions,
  fetchSampleInventoryEligible,
} from '@/api/samples'
import { useAuthStore } from '@/stores/auth'
import type {
  SampleInventoryEligibleRow,
  SampleFinishedGoodsOptions,
  SampleInventoryReceiptCreated,
  SampleInventoryReceiptLineInput,
} from '@/types/sample'

interface ReceiptDialogRow extends SampleInventoryEligibleRow {
  inputQuantity: string
  inputLocation: string
}

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [receipt: SampleInventoryReceiptCreated]
}>()

const authStore = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const rows = ref<ReceiptDialogRow[]>([])
const finishedOptions = ref<SampleFinishedGoodsOptions>({ warehouses: [], zones: [], locations: [] })
const finishedWarehouseId = ref('')
const finishedZoneId = ref('')
const finishedLocationId = ref('')
const loadState = ref<'ready' | 'empty' | 'error' | 'forbidden'>('ready')
const loadMessage = ref('')
const validationMessage = ref('')
const invalidQuantityIds = ref(new Set<string>())
const invalidLocationIds = ref(new Set<string>())
const invalidFinishedDestination = ref(false)
const inventoryConflict = ref(false)
let eligibleRequest = 0
const canCreateReceipt = computed(() => authStore.hasPermission('samples.add_sampleinventoryreceipt'))
const controlsDisabled = computed(() => loading.value || submitting.value || !canCreateReceipt.value)

const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => { if (!submitting.value) emit('update:modelValue', value) },
})

const enteredRows = computed(() => rows.value.filter((row) => row.inputQuantity.trim() !== ''))
const enteredCount = computed(() => enteredRows.value.length)
const finishedZones = computed(() => finishedOptions.value.zones.filter((item) => item.warehouse_id === finishedWarehouseId.value))
const finishedLocations = computed(() => finishedOptions.value.locations.filter((item) => item.zone_id === finishedZoneId.value))
const emptyText = computed(() => {
  if (loadState.value === 'forbidden') return loadMessage.value || '当前账号没有样品入库权限'
  if (loadState.value === 'error') return loadMessage.value || '可选样品加载失败'
  return '暂无符合入库条件的样品'
})

function resetDialog() {
  rows.value = []
  loadState.value = 'ready'
  loadMessage.value = ''
  validationMessage.value = ''
  invalidQuantityIds.value = new Set()
  invalidLocationIds.value = new Set()
  invalidFinishedDestination.value = false
  inventoryConflict.value = false
  finishedOptions.value = { warehouses: [], zones: [], locations: [] }
  finishedWarehouseId.value = ''
  finishedZoneId.value = ''
  finishedLocationId.value = ''
}

function getApiError(error: unknown): { status: number; message: string } {
  if (!(error instanceof AxiosError)) return { status: 0, message: '请求失败，请稍后重试。' }
  if (!error.response) return { status: 0, message: '网络连接异常，请检查后端服务后重试。' }
  const data = error.response.data as {
    error?: { message?: string; field_errors?: Record<string, unknown> }
    detail?: string
  }
  return {
    status: error.response.status,
    message: data?.error?.message || data?.detail || '请求失败，请稍后重试。',
  }
}

async function loadEligibleRows() {
  if (submitting.value) return
  const request = ++eligibleRequest
  if (!canCreateReceipt.value) {
    loadState.value = 'forbidden'
    loadMessage.value = '当前账号没有样品入库权限。'
    validationMessage.value = loadMessage.value
    loading.value = false
    return
  }
  loading.value = true
  loadMessage.value = ''
  invalidQuantityIds.value = new Set()
  invalidLocationIds.value = new Set()
  try {
    const [result, destinationOptions] = await Promise.all([
      fetchSampleInventoryEligible(),
      fetchSampleFinishedGoodsOptions(),
    ])
    if (request !== eligibleRequest || !props.modelValue) return
    // 接口按 100 条分页；滚动表格应包含后续候选项，而非只显示第一页。
    const eligibleRows = new Map(result.data.map(row => [row.sample_item_id, row]))
    for (let nextPage = 2; nextPage <= result.meta.total_pages; nextPage++) {
      const next = await fetchSampleInventoryEligible(nextPage)
      if (request !== eligibleRequest || !props.modelValue) return
      next.data.forEach(row => eligibleRows.set(row.sample_item_id, row))
    }
    finishedOptions.value = destinationOptions
    finishedWarehouseId.value = ''
    finishedZoneId.value = ''
    finishedLocationId.value = ''
    invalidFinishedDestination.value = false
    inventoryConflict.value = false
    if (destinationOptions.warehouses.length === 1) finishedWarehouseId.value = destinationOptions.warehouses[0].id
    const defaultZones = destinationOptions.zones.filter((item) => item.warehouse_id === finishedWarehouseId.value)
    if (defaultZones.length === 1) finishedZoneId.value = defaultZones[0].id
    rows.value = [...eligibleRows.values()].map((row) => ({
      ...row,
      inputQuantity: '',
      inputLocation: '样品库',
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

function clearRowValidation(row: ReceiptDialogRow) {
  const quantities = new Set(invalidQuantityIds.value)
  const locations = new Set(invalidLocationIds.value)
  quantities.delete(row.sample_item_id)
  locations.delete(row.sample_item_id)
  invalidQuantityIds.value = quantities
  invalidLocationIds.value = locations
}

function finishedWarehouseChanged() {
  finishedZoneId.value = ''
  finishedLocationId.value = ''
  const availableZones = finishedOptions.value.zones.filter((item) => item.warehouse_id === finishedWarehouseId.value)
  if (availableZones.length === 1) finishedZoneId.value = availableZones[0].id
  invalidFinishedDestination.value = false
}

function finishedZoneChanged() {
  finishedLocationId.value = ''
  invalidFinishedDestination.value = false
}

function validateRows(): SampleInventoryReceiptLineInput[] | null {
  const quantityErrors = new Set<string>()
  const locationErrors = new Set<string>()
  const messages: string[] = []

  if (!enteredRows.value.length) {
    validationMessage.value = '未填写任何入库数量，请至少填写一条大于 0 的入库数量。'
    return null
  }
  if (enteredRows.value.length > 100) {
    validationMessage.value = '一次最多提交 100 条样品明细，请分批入库。'
    return null
  }
  if (!finishedOptions.value.warehouses.some(item => item.id === finishedWarehouseId.value)
    || !finishedZones.value.some(item => item.id === finishedZoneId.value)
    || !finishedLocations.value.some(item => item.id === finishedLocationId.value && item.warehouse_id === finishedWarehouseId.value)) {
    invalidFinishedDestination.value = true
    validationMessage.value = '请选择成品入库仓库、库区和库位。'
    return null
  }

  const payload: SampleInventoryReceiptLineInput[] = []
  enteredRows.value.forEach((row, index) => {
    const quantity = Number(row.inputQuantity)
    if (!Number.isSafeInteger(quantity) || quantity <= 0) {
      quantityErrors.add(row.sample_item_id)
      messages.push(`第 ${index + 1} 条入库数量须为正整数`)
    } else if (quantity > row.remaining_quantity) {
      quantityErrors.add(row.sample_item_id)
      messages.push(`第 ${index + 1} 条最多可入库 ${row.remaining_quantity}`)
    }
    if (!row.inputLocation.trim()) {
      locationErrors.add(row.sample_item_id)
      messages.push(`第 ${index + 1} 条入库位置不能为空`)
    }
    if (
      Number.isSafeInteger(quantity)
      && quantity > 0
      && quantity <= row.remaining_quantity
      && row.inputLocation.trim()
    ) {
      payload.push({
        sample_item_id: row.sample_item_id,
        received_quantity: quantity,
        location: row.inputLocation.trim(),
        expected_cumulative_received: row.cumulative_received,
      })
    }
  })

  invalidQuantityIds.value = quantityErrors
  invalidLocationIds.value = locationErrors
  if (messages.length) {
    validationMessage.value = `校验：${messages.join('；')}。`
    return null
  }
  validationMessage.value = '校验通过，可以提交入库。'
  return payload
}

async function submitReceipt() {
  if (controlsDisabled.value || inventoryConflict.value || loadState.value !== 'ready') return
  const items = validateRows()
  if (!items) {
    ElMessage.warning(validationMessage.value)
    return
  }

  submitting.value = true
  try {
    const receipt = await createSampleInventoryReceipt(items, {
      warehouse_id: finishedWarehouseId.value,
      zone_id: finishedZoneId.value,
      location_id: finishedLocationId.value,
    })
    ElMessage.success(`样品与成品库存已同步入库，单号：${receipt.receipt_number}`)
    emit('created', receipt)
    emit('update:modelValue', false)
  } catch (error) {
    const result = getApiError(error)
    if (result.status === 409) {
      inventoryConflict.value = true
      validationMessage.value = '库存已变化，请刷新可选样品后重新提交。'
    } else if (result.status === 403) {
      validationMessage.value = '当前账号没有样品入库权限。'
    } else if (result.status === 401) {
      validationMessage.value = '登录状态已失效，请重新登录。'
    } else {
      validationMessage.value = result.message
    }
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
    } else { eligibleRequest++; loading.value = false }
  },
  { immediate: true },
)
onBeforeUnmount(() => { eligibleRequest++ })
</script>

<template>
  <ElDialog
    v-model="dialogVisible"
    title="批量入库样品"
    class="sample-batch-dialog sample-receipt-dialog"
    modal-class="sample-receipt-overlay"
    data-figma-node="814:8933"
    width="min(1500px, calc(100vw - 32px))"
    :height="500"
    align-center
    draggable
    overflow
    append-to-body
    destroy-on-close
    :show-close="!submitting"
    :close-on-click-modal="false"
    :close-on-press-escape="!submitting"
  >
    <div class="receipt-dialog-content batch-dialog-content">
      <section class="finished-destination" :class="{ 'is-invalid': invalidFinishedDestination }" aria-label="成品仓入库位置">
        <div class="destination-heading">
          <strong>成品仓入库位置</strong>
        </div>
        <ElSelect v-model="finishedWarehouseId" aria-label="成品仓" :disabled="controlsDisabled" placeholder="选择成品仓" @change="finishedWarehouseChanged">
          <ElOption v-for="item in finishedOptions.warehouses" :key="item.id" :value="item.id" :label="`${item.warehouse_number} · ${item.warehouse_name}`" />
        </ElSelect>
        <ElSelect v-model="finishedZoneId" aria-label="成品库区" :disabled="controlsDisabled || !finishedWarehouseId" placeholder="选择库区" @change="finishedZoneChanged">
          <ElOption v-for="item in finishedZones" :key="item.id" :value="item.id" :label="item.zone_name" />
        </ElSelect>
        <ElSelect v-model="finishedLocationId" aria-label="成品库位" filterable :disabled="controlsDisabled || !finishedZoneId" placeholder="选择库位" @change="invalidFinishedDestination = false">
          <ElOption v-for="item in finishedLocations" :key="item.id" :value="item.id" :label="item.location_number" />
        </ElSelect>
      </section>

      <section class="receipt-detail-panel batch-detail-panel" aria-label="可入库样品明细">
        <ElTable
          v-loading="loading"
          :data="rows"
          row-key="sample_item_id"
          height="290"
          :empty-text="emptyText"
        >
          <ElTableColumn prop="sample_request_number" label="样品跟进单号" width="150" show-overflow-tooltip />
          <ElTableColumn prop="flow_condition" label="流程条件" width="156" show-overflow-tooltip />
          <ElTableColumn label="产品类别" width="100" show-overflow-tooltip>
            <template #default="{ row }">{{ row.product_category || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn prop="product_name" label="产品名称" width="130" show-overflow-tooltip />
          <ElTableColumn prop="specification" label="规格" min-width="150" show-overflow-tooltip />
          <ElTableColumn prop="color" label="颜色" width="90" show-overflow-tooltip />
          <ElTableColumn prop="sampling_quantity" label="打样" width="58" align="center" />
          <ElTableColumn prop="cumulative_received" label="累计入库" width="72" align="center" />
          <ElTableColumn prop="remaining_quantity" label="剩余" width="58" align="center" />
          <ElTableColumn label="入库数量 *" width="112">
            <template #default="{ row }">
              <ElInput
                v-model="row.inputQuantity"
                class="line-input quantity-input"
                :class="{ 'is-invalid': invalidQuantityIds.has(row.sample_item_id) }"
                type="number"
                min="1"
                :max="row.remaining_quantity"
                inputmode="numeric"
                :aria-label="`${row.sample_request_number} 入库数量`"
                placeholder="数量"
                :disabled="controlsDisabled"
                @input="clearRowValidation(row)"
              />
            </template>
          </ElTableColumn>
          <ElTableColumn label="入库位置 *" width="124">
            <template #default="{ row }">
              <ElInput
                v-model="row.inputLocation"
                class="line-input location-input"
                :class="{ 'is-invalid': invalidLocationIds.has(row.sample_item_id) }"
                maxlength="150"
                :aria-label="`${row.sample_request_number} 入库位置`"
                :disabled="controlsDisabled"
                @input="clearRowValidation(row)"
              />
            </template>
          </ElTableColumn>
        </ElTable>

      </section>
    </div>

    <template #footer>
      <div class="receipt-dialog-footer batch-dialog-footer">
        <div class="footer-status">
          <span>已填写 {{ enteredCount }} 条样品明细</span>
          <ElButton
            v-if="loadState === 'error' || loadState === 'forbidden' || inventoryConflict"
            link
            type="primary"
            :icon="Refresh"
            :loading="loading"
            :disabled="submitting || !canCreateReceipt"
            @click="loadEligibleRows"
          >重新加载</ElButton>
        </div>
        <div class="footer-actions">
          <ElButton :disabled="submitting" @click="closeDialog">取消</ElButton>
          <ElButton
            type="primary"
            :loading="submitting"
            :disabled="controlsDisabled || inventoryConflict || loadState !== 'ready'"
            @click="submitReceipt"
          >确认入库</ElButton>
        </div>
      </div>
    </template>
  </ElDialog>
</template>

<style lang="scss" src="./sampleInventoryReceiptDialog.scss"></style>
