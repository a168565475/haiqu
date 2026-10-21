<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { fetchInventoryOptions, fetchOutboundBatches, createFinishedGoodsOutbound } from '@/api/inventory'
import type { FinishedGoodsReceipt, InventoryOptions } from '@/types/inventory'

type OutboundRow = FinishedGoodsReceipt & { outbound_quantity: number; outbound_quantity_per_box: number }
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const submitting = ref(false)
const errorMessage = ref('')
const rows = ref<OutboundRow[]>([])
const loadingImages = ref<File[]>([])
const options = ref<InventoryOptions>({ warehouses: [], zones: [], locations: [], suppliers: [], product_colors: [], production_orders: [], employees: [] })
const form = reactive({ responsible_employee_id: '', shipment_date: new Date().toLocaleDateString('sv-SE'), loading_fee: 0 as number | null, other_fee: 0 as number | null, remark: '' })
const receiptIds = computed(() => String(route.query.receipt_ids || '').split(',').map(value => value.trim()).filter(Boolean))
const selectedRows = computed(() => rows.value.filter(row => Number(row.outbound_quantity) > 0))
const number = (value: number | string | null | undefined) => Number(value || 0).toLocaleString('zh-CN')
const message = (error: unknown) => error instanceof AxiosError ? (error.response?.data as { error?: { message?: string } })?.error?.message || '请求失败，请重试。' : '请求失败，请重试。'

async function load() {
  if (!receiptIds.value.length) { errorMessage.value = '没有可出库的库存批次，请从库存汇总选择记录。'; return }
  loading.value = true; errorMessage.value = ''
  try {
    const [batches, inventoryOptions] = await Promise.all([fetchOutboundBatches(receiptIds.value), fetchInventoryOptions()])
    rows.value = batches.map(row => ({ ...row, outbound_quantity: 0, outbound_quantity_per_box: row.quantity_per_box || 1 }))
    options.value = { ...options.value, ...inventoryOptions }
  } catch (error) { errorMessage.value = message(error) }
  finally { loading.value = false }
}
function handleUploadChange(_file: UploadFile, fileList: UploadFile[]) {
  loadingImages.value = fileList.flatMap(file => file.raw ? [file.raw as unknown as File] : [])
}
function removeRow(row: OutboundRow) { row.outbound_quantity = 0 }
async function submit() {
  if (submitting.value) return
  if (!form.responsible_employee_id) { ElMessage.warning('请选择出库负责人。'); return }
  if (!form.shipment_date) { ElMessage.warning('请选择出货日期。'); return }
  if (!selectedRows.value.length) { ElMessage.warning('请至少填写一条出库数量。'); return }
  if (new Set(selectedRows.value.map(row => row.task_number_snapshot)).size !== 1) { ElMessage.warning('一张出货单只能包含同一生产任务单的库存。'); return }
  if (selectedRows.value.some(row => !Number.isInteger(row.outbound_quantity) || !Number.isInteger(row.outbound_quantity_per_box) || row.outbound_quantity_per_box < 1)) { ElMessage.warning('出库数量和每箱数量必须填写正整数。'); return }
  if (loadingImages.value.length > 20 || loadingImages.value.some(file => !/\.(jpe?g|png|gif|webp)$/i.test(file.name) || file.size <= 0 || file.size > 5 * 1024 * 1024)) { ElMessage.warning('最多上传 20 张 JPG、PNG、GIF 或 WebP 图片，单张不能超过 5MB。'); return }
  submitting.value = true
  try {
    const result = await createFinishedGoodsOutbound({
      responsible_employee_id: form.responsible_employee_id,
      shipment_date: form.shipment_date,
      loading_fee: form.loading_fee ?? 0,
      other_fee: form.other_fee ?? 0,
      remark: form.remark,
      items: selectedRows.value.map(row => ({ receipt_id: row.id, expected_remaining_quantity: row.remaining_quantity, outbound_quantity: row.outbound_quantity, quantity_per_box: row.outbound_quantity_per_box })),
    }, loadingImages.value)
    ElMessage.success('出库单已生成。')
    await router.push({ name: 'finished-goods-outbound-detail', params: { outboundId: result.id } })
  } catch (error) { ElMessage.error(message(error)) }
  finally { submitting.value = false }
}
onMounted(() => { void load() })
</script>

<template>
  <section class="outbound-form-page" v-loading="loading">
    <header class="page-heading"><div><p class="breadcrumb">仓库管理 / 成品库存 / 新建出库</p><h1>新建成品出库</h1><p class="sub-title">按选中的生产任务库存批次生成出货单，库存数量提交时再次校验。</p></div><ElButton @click="router.back()">返回</ElButton></header>
    <ElAlert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
    <section v-else class="form-card">
      <div class="card-heading"><h2>出库明细</h2><span>已选择 {{ selectedRows.length }} 条</span></div>
      <div class="table-wrap"><table class="erp-table-editor"><thead><tr><th>生产任务单号</th><th>产品编码</th><th>类别</th><th>品名</th><th>货号</th><th>材质</th><th>规格</th><th>颜色</th><th>仓库 / 库位</th><th>可出库</th><th>出库数量</th><th>每箱数量</th><th>操作</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.task_number_snapshot || '—' }}</td><td>{{ row.product_code_snapshot || '—' }}</td><td>{{ row.category_snapshot || '—' }}</td><td>{{ row.product_name_snapshot || '—' }}</td><td>{{ row.item_number_snapshot || '—' }}</td><td>{{ row.material_snapshot || '—' }}</td><td>{{ row.specification_snapshot || '—' }}</td><td>{{ row.actual_color || '—' }}</td><td>{{ row.warehouse_name }} / {{ row.location_number }}</td><td>{{ number(row.remaining_quantity) }} {{ row.unit_name }}</td><td><ElInputNumber v-model="row.outbound_quantity" :min="0" :max="row.remaining_quantity" :step="1" controls-position="right"><template #suffix>{{ row.unit_name }}</template></ElInputNumber></td><td><ElInputNumber v-model="row.outbound_quantity_per_box" :min="1" :step="1" controls-position="right"><template #suffix>{{ row.unit_name }}/箱</template></ElInputNumber></td><td><ElButton link type="primary" @click="removeRow(row)">清零</ElButton></td></tr></tbody></table><p v-if="!rows.length" class="empty">暂无可出库批次</p></div>
      <ElForm label-position="top" class="form-grid erp-flat-form"><ElFormItem label="出库负责人" required><ElSelect v-model="form.responsible_employee_id" filterable placeholder="请选择在职员工"><ElOption v-for="employee in options.employees || []" :key="employee.id" :value="employee.id" :label="`${employee.display_name}${employee.employee_code ? `（${employee.employee_code}）` : ''}`" /></ElSelect></ElFormItem><ElFormItem label="出货日期" required><ElDatePicker v-model="form.shipment_date" type="date" value-format="YYYY-MM-DD" /></ElFormItem><ElFormItem label="装卸费用"><ElInputNumber v-model="form.loading_fee" :min="0" :precision="2" controls-position="right" /></ElFormItem><ElFormItem label="其他费用"><ElInputNumber v-model="form.other_fee" :min="0" :precision="2" controls-position="right" /></ElFormItem><ElFormItem label="装卸图片"><ElUpload action="#" :auto-upload="false" multiple accept="image/*" :on-change="handleUploadChange" :on-remove="handleUploadChange"><ElButton type="primary" class="loading-image-button">选择图片</ElButton><template #tip><span class="upload-tip">最多 20 张 JPG、PNG、GIF 或 WebP 图片，单张不超过 5MB。</span></template></ElUpload></ElFormItem><ElFormItem label="备注" class="remark-item"><ElInput v-model="form.remark" type="textarea" :rows="3" maxlength="3000" show-word-limit /></ElFormItem></ElForm>
      <footer class="form-footer"><span>出库后系统会生成出货单，并扣减对应入库批次的可用库存。</span><div><ElButton @click="router.back()">取消</ElButton><ElButton type="primary" :loading="submitting" @click="submit">生成出货单</ElButton></div></footer>
    </section>
  </section>
</template>

<style scoped lang="scss">
.outbound-form-page { box-sizing: border-box; min-width: 0; padding: 0; color: var(--erp-color-text-primary); }
.page-heading,.card-heading,.form-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.breadcrumb,.sub-title { margin: 0 0 6px; color: var(--erp-color-text-secondary); font-size: 13px; }
h1 { margin: 0; font-size: 28px; } h2 { margin: 0; font-size: 18px; }
.form-card { margin-top: 14px; padding: 20px; border: 1px solid var(--erp-color-border); border-radius: 12px; background: var(--erp-color-surface); }
.table-wrap { margin-top: 16px; overflow-x: auto; border: 1px solid var(--erp-table-grid); border-radius: 8px; }
table { width: 100%; min-width: 1700px; border-collapse: collapse; font-size: 13px; } th,td { padding: 10px 12px; border-bottom: 1px solid var(--erp-table-grid); text-align: left; white-space: nowrap; } th { color: var(--erp-table-header-text); background: var(--erp-table-header-background); font-weight: 600; } tbody tr:last-child td { border-bottom: 0; }
.empty { padding: 32px; color: var(--erp-color-text-secondary); text-align: center; }
.form-grid { display: grid; grid-template-columns: repeat(4, minmax(180px, 1fr)); gap: 2px 18px; margin-top: 20px; } :deep(.el-form-item) { margin-bottom: 12px; } :deep(.el-select), :deep(.el-date-editor), :deep(.el-input-number) { width: 100%; } .remark-item { grid-column: span 2; } .upload-tip { color: var(--erp-color-text-secondary); font-size: 12px; }
.form-footer { margin-top: 12px; padding-top: 16px; border-top: 1px solid var(--erp-color-border-subtle); color: var(--erp-color-text-secondary); font-size: 12px; }
.loading-image-button { min-width: 112px; }
.upload-tip { display: block; margin-top: 8px; line-height: 18px; }
@media (max-width: 1100px) { .form-grid { grid-template-columns: repeat(2, minmax(180px, 1fr)); } }
</style>
