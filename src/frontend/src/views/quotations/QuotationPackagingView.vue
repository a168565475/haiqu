<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Box, Check, Delete, EditPen } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { AxiosError } from 'axios'

import { createContainerTier, deleteContainerTier, fetchContainerTiers, fetchQuotation, fetchQuotationVersion, saveQuotationLinePackaging } from '@/api/quotations'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { QuotationContainerTier, QuotationDetail, QuotationLine, QuotationLinePackaging, QuotationVersionDetail } from '@/types/quotation'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const quotation = ref<QuotationDetail | null>(null)
const version = ref<QuotationVersionDetail | null>(null)
const line = ref<QuotationLine | null>(null)
const versionEtag = ref('')
const containerTiers = ref<QuotationContainerTier[]>([])
const containerDialogVisible = ref(false)
const loading = ref(true)
const saving = ref(false)
const errorMessage = ref('')
const originalFormPayload = ref('')
const form = reactive({
  length_cm: '', width_cm: '', height_cm: '', pieces_per_carton: '', carton_count: '',
  gross_weight_kg: '', net_weight_kg: '',
})
const containerForm = reactive({
  container_type_code: '',
  effective_volume_cbm: '',
  load_factor_percent: '',
  unit_price: '',
})

const quotationId = computed(() => String(route.params.quotationId || ''))
const lineId = computed(() => String(route.params.lineId || ''))
const editable = computed(() => Boolean(version.value?.status === 'DRAFT' && authStore.canFor('quotations.change_quotationline', version.value)))
const canAddContainerTier = computed(() => Boolean(version.value?.status === 'DRAFT' && authStore.canFor('quotations.add_quotationcontainertier', version.value)))
const canDeleteContainerTier = computed(() => Boolean(version.value?.status === 'DRAFT' && authStore.canFor('quotations.delete_quotationcontainertier', version.value)))
const lineIndex = computed(() => version.value?.lines.findIndex((item) => item.id === lineId.value) ?? -1)
const linePosition = computed(() => lineIndex.value >= 0 ? `${lineIndex.value + 1}/${version.value?.lines.length || 0}` : '—')
const previousLine = computed(() => lineIndex.value > 0 ? version.value?.lines[lineIndex.value - 1] || null : null)
const nextLine = computed(() => lineIndex.value >= 0 && lineIndex.value < (version.value?.lines.length || 0) - 1 ? version.value?.lines[lineIndex.value + 1] || null : null)
const hasUnsavedChanges = computed(() => originalFormPayload.value !== JSON.stringify(form))

function formatThreeDecimal(value: bigint): string {
  return `${value / 1000n}.${(value % 1000n).toString().padStart(3, '0')}`
}

function parseDimension(value: string): bigint | null {
  const match = value.trim().match(/^(\d+)(?:\.(\d{0,4}))?$/)
  if (!match) return null
  const scaled = BigInt(match[1]) * 10_000n + BigInt((match[2] || '').padEnd(4, '0') || '0')
  return scaled > 0n ? scaled : null
}

function formatCbm(value: string): string | null {
  const match = value.trim().match(/^(\d+)(?:\.(\d+))?$/)
  if (!match) return null
  const fraction = (match[2] || '').padEnd(4, '0')
  let thousandths = BigInt(match[1]) * 1000n + BigInt(fraction.slice(0, 3))
  if (fraction[3] >= '5') thousandths += 1n
  return formatThreeDecimal(thousandths)
}

const cartonCbmPreview = computed(() => {
  const length = parseDimension(form.length_cm)
  const width = parseDimension(form.width_cm)
  const height = parseDimension(form.height_cm)
  if (length === null || width === null || height === null) return '—'
  const scaledCbm = length * width * height
  return formatThreeDecimal((scaledCbm * 1000n + 500_000_000_000_000_000n) / 1_000_000_000_000_000_000n)
})
const totalCbm = computed(() => {
  const cartonCbm = cartonCbmPreview.value === '—' ? null : formatCbm(cartonCbmPreview.value)
  if (!cartonCbm || !/^\d+$/.test(form.carton_count.trim())) return '—'
  const [whole, fraction] = cartonCbm.split('.')
  return formatThreeDecimal((BigInt(whole) * 1000n + BigInt(fraction)) * BigInt(form.carton_count.trim()))
})
const packagingReady = computed(() => Boolean(line.value?.packaging && Number(line.value.packaging.carton_cbm) > 0))
const containerTiersReady = computed(() => containerTiers.value.length > 0)
const configurationReady = computed(() => packagingReady.value && containerTiersReady.value)
const validationItemsMissing = computed(() => [
  Boolean(line.value?.specification_snapshot && line.value?.unit_code),
  packagingReady.value,
  containerTiersReady.value,
].filter((ready) => !ready).length)
const completionReason = computed(() => {
  if (!packagingReady.value) return '请先保存包装与箱规。'
  if (!containerTiersReady.value) return '请先按报价保存至少一条装柜数量档。'
  return '完成后进入固定模板预览与发送。'
})
const containerPreview = computed(() => {
  const cartonCbm = Number(line.value?.packaging?.carton_cbm)
  const volume = Number(containerForm.effective_volume_cbm)
  const loadFactor = Number(containerForm.load_factor_percent) / 100
  const pieces = Number(line.value?.packaging?.pieces_per_carton)
  if (!Number.isFinite(cartonCbm) || cartonCbm <= 0 || !Number.isFinite(volume) || volume <= 0 || !Number.isFinite(loadFactor) || loadFactor <= 0 || loadFactor > 1 || !Number.isInteger(pieces) || pieces <= 0) return null
  const cartons = Math.floor((volume * loadFactor) / cartonCbm)
  return { cartons, quantity: cartons * pieces }
})

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络异常，当前输入已保留，请检查连接后重试。'
  const payload = error.response.data as { detail?: string; error?: { message?: string; field_errors?: Record<string, string[]> } }
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有编辑包装配置的权限。'
  if (error.response.status === 409) return '当前装柜参数已存在或不符合业务规则。'
  if (error.response.status === 412) return '报价已被其他人更新，请重新加载后重试。'
  if (error.response.status === 428) return '缺少数据版本，请重新加载后重试。'
  if (error.response.status >= 500) return '报价服务暂时异常，请稍后重试。'
  const fields = payload.error?.field_errors
  return fields ? Object.values(fields).flat().join('；') : payload.error?.message || payload.detail || '保存失败，请检查输入。'
}

function populatePackaging(packaging?: QuotationLinePackaging | null) {
  Object.assign(form, packaging ? {
    length_cm: packaging.length_cm, width_cm: packaging.width_cm, height_cm: packaging.height_cm,
    pieces_per_carton: String(packaging.pieces_per_carton), carton_count: String(packaging.carton_count),
    gross_weight_kg: packaging.gross_weight_kg || '', net_weight_kg: packaging.net_weight_kg || '',
  } : { length_cm: '', width_cm: '', height_cm: '', pieces_per_carton: '', carton_count: '', gross_weight_kg: '', net_weight_kg: '' })
  originalFormPayload.value = JSON.stringify(form)
}

async function loadPage() {
  if (!quotationId.value || !lineId.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const quotationResult = await fetchQuotation(quotationId.value)
    quotation.value = quotationResult.data
    if (!quotationResult.data.current_version) throw new Error('该报价尚未创建版本。')
    const versionResult = await fetchQuotationVersion(quotationResult.data.current_version.id)
    version.value = versionResult.data
    versionEtag.value = versionResult.etag
    const currentLine = versionResult.data.lines.find(item => item.id === lineId.value)
    if (!currentLine) throw new Error('未找到指定报价产品行。')
    line.value = currentLine
    populatePackaging(currentLine.packaging)
    const tiersResult = await fetchContainerTiers(lineId.value)
    containerTiers.value = tiersResult.data
    versionEtag.value = tiersResult.etag || versionEtag.value
  } catch (error) {
    errorMessage.value = error instanceof Error && !('response' in error) ? error.message : getErrorMessage(error)
  } finally {
    loading.value = false
  }
}

function numericPayload() {
  return {
    length_cm: form.length_cm,
    width_cm: form.width_cm,
    height_cm: form.height_cm,
    pieces_per_carton: Number(form.pieces_per_carton),
    carton_count: Number(form.carton_count),
    gross_weight_kg: form.gross_weight_kg || null,
    net_weight_kg: form.net_weight_kg || null,
  }
}

async function savePackaging() {
  if (!line.value || !editable.value) return
  if (![form.length_cm, form.width_cm, form.height_cm, form.pieces_per_carton, form.carton_count].every(value => Number(value) > 0)) {
    ElMessage.warning('请填写大于 0 的包装尺寸、每箱件数和箱数。')
    return
  }
  if (!Number.isInteger(Number(form.pieces_per_carton)) || !Number.isInteger(Number(form.carton_count))) {
    ElMessage.warning('每箱件数和箱数必须填写正整数。')
    return
  }
  const cartonCbm = Number(form.length_cm) * Number(form.width_cm) * Number(form.height_cm) / 1_000_000
  if (cartonCbm < 0.0005) {
    ElMessage.warning('当前尺寸换算后不足 0.001 m³，请检查长、宽、高。')
    return
  }
  saving.value = true
  try {
    const result = await saveQuotationLinePackaging(line.value.id, numericPayload(), versionEtag.value)
    versionEtag.value = result.etag
    line.value = { ...line.value, packaging: result.data }
    originalFormPayload.value = JSON.stringify(form)
    ElMessage.success('包装信息已保存；已有装柜数量档已按当前参数重新计算。')
    const tiersResult = await fetchContainerTiers(line.value.id)
    containerTiers.value = tiersResult.data
    versionEtag.value = tiersResult.etag || versionEtag.value
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    saving.value = false
  }
}

function openContainerDialog() {
  if (!line.value || !canAddContainerTier.value) return
  if (!line.value.packaging) {
    ElMessage.warning('请先保存包装信息。')
    return
  }
  Object.assign(containerForm, { container_type_code: '', effective_volume_cbm: '', load_factor_percent: '', unit_price: line.value.unit_price || '' })
  containerDialogVisible.value = true
}

async function saveContainerTier() {
  if (!line.value || !canAddContainerTier.value) return
  const containerTypeCode = containerForm.container_type_code.trim().toUpperCase()
  const effectiveVolume = Number(containerForm.effective_volume_cbm)
  const loadFactorPercent = Number(containerForm.load_factor_percent)
  const unitPrice = Number(containerForm.unit_price)
  if (!/^[A-Z0-9_-]+$/.test(containerTypeCode)) {
    ElMessage.warning('柜型仅支持大写字母、数字、下划线和短横线。')
    return
  }
  if (!Number.isFinite(effectiveVolume) || effectiveVolume <= 0) {
    ElMessage.warning('可用容积必须大于 0。')
    return
  }
  if (!Number.isFinite(loadFactorPercent) || loadFactorPercent <= 0 || loadFactorPercent > 100) {
    ElMessage.warning('装载系数必须在 0 到 100 之间。')
    return
  }
  if (!Number.isFinite(unitPrice) || unitPrice < 0) {
    ElMessage.warning('装柜单价必须是大于或等于 0 的数字。')
    return
  }
  if (containerTiers.value.some(tier => tier.container_type_code === containerTypeCode)) {
    ElMessage.warning('当前报价行已存在该柜型数量档。')
    return
  }
  saving.value = true
  try {
    const result = await createContainerTier(line.value.id, {
      container_type_code: containerTypeCode,
      effective_volume_cbm: containerForm.effective_volume_cbm,
      load_factor: String(loadFactorPercent / 100),
      unit_price: containerForm.unit_price,
    }, versionEtag.value)
    versionEtag.value = result.etag
    containerTiers.value = [...containerTiers.value, result.data]
    containerDialogVisible.value = false
    ElMessage.success('已按当前报价保存装柜数量档，并完成数量计算。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    saving.value = false
  }
}

async function removeContainerTier(tier: QuotationContainerTier) {
  if (!canDeleteContainerTier.value) return
  saving.value = true
  try {
    versionEtag.value = await deleteContainerTier(tier.id, versionEtag.value)
    containerTiers.value = containerTiers.value.filter(item => item.id !== tier.id)
    ElMessage.success('装柜数量档已删除。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    saving.value = false
  }
}

function backToEditor() { void router.push({ name: 'quotation-edit', params: { quotationId: quotationId.value } }) }

async function confirmLeaveIfDirty(): Promise<boolean> {
  if (!hasUnsavedChanges.value) return true
  try {
    await ElMessageBox.confirm('包装信息尚未保存，离开后当前输入将丢失。', '未保存修改', { type: 'warning' })
    return true
  } catch {
    return false
  }
}

async function navigateLine(target: QuotationLine | null) {
  if (!target || !(await confirmLeaveIfDirty())) return
  await router.push({ name: 'quotation-packaging', params: { quotationId: quotationId.value, lineId: target.id } })
}

async function completeConfiguration() {
  if (!configurationReady.value) {
    ElMessage.warning(completionReason.value)
    return
  }
  if (!(await confirmLeaveIfDirty())) return
  await router.push({ name: 'quotation-preview', params: { quotationId: quotationId.value } })
}

onMounted(() => { void loadPage() })
watch(lineId, (current, previous) => { if (current && current !== previous) void loadPage() })
</script>

<template>
  <section v-loading="loading" class="quotation-packaging-page" aria-label="报价包装与装柜配置">
    <template v-if="quotation && version && line">
      <header class="page-header">
        <div>
          <div class="title-row"><h1>包装与装柜配置</h1><ElTag size="small">{{ version.status_display }}</ElTag></div>
          <p>{{ quotation.quotation_number }} / V{{ version.version_number }} · 产品 {{ linePosition }} · {{ version.lines.length }}</p>
        </div>
        <div class="header-actions"><span v-if="line.packaging" class="packaging-saved"><ElIcon><Check /></ElIcon> 包装信息已保存</span><ElButton class="black-button" :loading="saving" :disabled="!editable" @click="savePackaging">保存包装信息</ElButton></div>
      </header>

      <section class="configuration-steps" aria-label="包装配置步骤">
        <b class="is-complete"><span class="step-index">1</span><span class="step-copy"><span>产品规格<span class="compact-check"> ✓</span></span><small>完成</small></span></b>
        <b class="is-current"><span class="step-index">2</span><span class="step-copy"><span>包装参数</span><small>当前</small></span></b>
        <b><span class="step-index">3</span><span class="step-copy"><span>装柜数量档</span><small>可后补</small></span></b>
        <b><span class="step-index">4</span><span class="step-copy"><span>校验汇总</span><small>待完成</small></span></b>
      </section>

      <div class="page-layout">
        <main class="page-main">
          <section class="product-strip">
            <span class="product-icon"><ElIcon><Box /></ElIcon></span>
            <div><b>{{ line.product_description_snapshot }}</b><small>{{ line.specification_snapshot || '未维护规格' }} · {{ line.quantity }} {{ line.unit_code }}</small><small v-if="line.notes">{{ line.notes }}</small></div>
            <ElTag size="small" :type="line.specification_snapshot && line.unit_code ? 'success' : 'warning'">{{ line.specification_snapshot && line.unit_code ? '规格完整' : '规格待完善' }}</ElTag>
            <div class="line-nav"><ElButton v-if="previousLine" size="small" @click="navigateLine(previousLine)">上一行</ElButton><ElButton size="small" :disabled="!nextLine" @click="navigateLine(nextLine)">下一行</ElButton></div>
          </section>
          <ElCard class="detail-card" shadow="never">
            <template #header><div class="card-title"><b>包装与箱规</b><span>填写外箱尺寸、每箱件数和箱数；毛重、净重可选。</span></div></template>
            <ElForm label-position="top" class="packaging-form">
              <div class="dimension-grid"><ElFormItem label="长"><ElInput v-model="form.length_cm" inputmode="decimal" :disabled="!editable"><template #append>cm</template></ElInput></ElFormItem><ElFormItem label="宽"><ElInput v-model="form.width_cm" inputmode="decimal" :disabled="!editable"><template #append>cm</template></ElInput></ElFormItem><ElFormItem label="高"><ElInput v-model="form.height_cm" inputmode="decimal" :disabled="!editable"><template #append>cm</template></ElInput></ElFormItem><ElFormItem label="每箱"><ElInput v-model="form.pieces_per_carton" inputmode="numeric" :disabled="!editable"><template #append>{{ line.unit_code }}</template></ElInput></ElFormItem><ElFormItem label="箱数"><ElInput v-model="form.carton_count" inputmode="numeric" :disabled="!editable"><template #append>CTN</template></ElInput></ElFormItem><ElFormItem label="毛重"><ElInput v-model="form.gross_weight_kg" inputmode="decimal" :disabled="!editable"><template #append>kg</template></ElInput></ElFormItem><ElFormItem label="净重"><ElInput v-model="form.net_weight_kg" inputmode="decimal" :disabled="!editable"><template #append>kg</template></ElInput></ElFormItem><ElFormItem label="CBM"><ElInput :model-value="cartonCbmPreview === '—' ? '' : `${cartonCbmPreview} m³`" disabled /></ElFormItem></div>
              <p class="formula">单箱体积 = {{ form.length_cm || '长' }} × {{ form.width_cm || '宽' }} × {{ form.height_cm || '高' }} ÷ 1,000,000{{ cartonCbmPreview === '—' ? '' : ` = ${cartonCbmPreview} m³` }}，保留 3 位小数。</p>
            </ElForm>
          </ElCard>

          <ElCard class="detail-card" shadow="never">
            <template #header><div class="card-title"><b>装柜数量档</b><span>{{ containerTiers.length }} 条</span><ElButton class="black-button" :disabled="!canAddContainerTier || !line.packaging" :loading="saving" @click="openContainerDialog">＋ 新增装柜数量档</ElButton></div></template>
            <ElTable :data="containerTiers" empty-text="暂无装柜数量档。"><ElTableColumn label="柜型" min-width="94"><template #default="{ row }"><b>{{ row.container_type_code }}</b></template></ElTableColumn><ElTableColumn label="容积/系数" min-width="130"><template #default="{ row }">{{ row.effective_volume_cbm }}m³ / {{ (Number(row.load_factor) * 100).toFixed(0) }}%</template></ElTableColumn><ElTableColumn prop="auto_carton_count" label="可装箱数" min-width="102"/><ElTableColumn label="报价数量" min-width="112"><template #default="{ row }"><b>{{ row.final_quantity }} {{ line.unit_code }}</b></template></ElTableColumn><ElTableColumn label="装柜单价" min-width="110"><template #default="{ row }">{{ version.currency_code }} {{ row.unit_price }}</template></ElTableColumn><ElTableColumn label="状态" min-width="72"><template #default="{ row }">{{ row.manual_carton_count === null ? '自动' : '已调整' }}</template></ElTableColumn><ElTableColumn v-if="canDeleteContainerTier" class-name="tier-row-action" label="操作" width="112" fixed="right"><template #default="{ row }"><ElButton text type="danger" :icon="Delete" @click="removeContainerTier(row)">删除</ElButton></template></ElTableColumn></ElTable>
            <p class="tier-footnote">ⓘ 装柜配置仅用于当前报价产品。</p>
          </ElCard>

        </main>
        <aside class="summary-column">
          <ElCard shadow="never" class="summary-card"><template #header><div class="summary-title"><b>配置汇总</b><ElTag size="small" :type="configurationReady ? 'success' : 'warning'">{{ configurationReady ? '已完成' : `${validationItemsMissing}项待完善` }}</ElTag></div></template><div class="summary-line"><small>产品 {{ linePosition }}</small><strong>{{ line.product_description_snapshot }}</strong><b>{{ line.quantity }} {{ line.unit_code }}</b></div><h3>包装计算</h3><p><span>单箱体积</span><b>{{ line.packaging ? `${line.packaging.carton_cbm} m³` : '—' }}</b></p><p><span>每箱数量</span><b>{{ form.pieces_per_carton ? `${form.pieces_per_carton} ${line.unit_code}` : '—' }}</b></p><p><span>总箱数</span><b>{{ form.carton_count ? `${form.carton_count} CTN` : '—' }}</b></p><p><span>总体积</span><b>{{ totalCbm === '—' ? '—' : `${totalCbm} m³` }}</b></p><h3>完善情况</h3><p :class="['validation', { warning: !(line.specification_snapshot && line.unit_code) }] "><ElIcon><Check v-if="line.specification_snapshot && line.unit_code"/><EditPen v-else/></ElIcon> {{ line.specification_snapshot && line.unit_code ? '产品规格与单位完整' : '产品规格待完善' }}</p><p :class="['validation', { warning: !packagingReady }] "><ElIcon><Check v-if="packagingReady"/><EditPen v-else/></ElIcon> {{ packagingReady ? '包装信息已保存' : '包装信息尚未保存' }}</p><p :class="['validation', { warning: !containerTiersReady }] "><ElIcon><Check v-if="containerTiersReady"/><EditPen v-else/></ElIcon> {{ containerTiersReady ? '装柜数量档已配置' : '装柜数量档未配置' }}</p><ElAlert v-if="!containerTiersReady" title="请先保存包装信息，再新增至少 1 条装柜数量档。" type="warning" :closable="false" /><div class="summary-actions"><ElButton class="black-button" :disabled="!editable || !configurationReady" :title="completionReason" @click="completeConfiguration">完成配置并预览</ElButton></div><small class="summary-footnote">{{ completionReason }}</small></ElCard>
        </aside>
      </div>
      <AppWindowDialog v-model="containerDialogVisible" class="quotation-container-dialog" title="新增装柜数量档" :width="850" :height="700" :close-on-click-modal="false">
        <p class="dialog-subtitle">仅对当前报价产品生效。</p>
        <div class="container-product-snapshot"><span class="container-product-icon"><ElIcon><Box /></ElIcon></span><div><b>{{ line.product_description_snapshot }}</b><small>{{ quotation.quotation_number }} / V{{ version.version_number }} · {{ line.specification_snapshot || '规格待维护' }}</small></div><ElTag type="success" round>✓ 包装已保存</ElTag></div>
        <ElForm label-position="top" class="container-dialog-form">
          <ElFormItem label="柜型"><ElInput v-model="containerForm.container_type_code" placeholder="例如 40HQ" maxlength="30" :disabled="saving" @input="containerForm.container_type_code = containerForm.container_type_code.toUpperCase()" /></ElFormItem>
          <ElFormItem label="可用容积"><ElInput v-model="containerForm.effective_volume_cbm" inputmode="decimal" placeholder="例如 68.000" :disabled="saving"><template #append>m³</template></ElInput></ElFormItem>
          <ElFormItem label="装载系数"><ElInput v-model="containerForm.load_factor_percent" inputmode="decimal" placeholder="例如 90" :disabled="saving"><template #append>%</template></ElInput></ElFormItem>
          <ElFormItem label="装柜单价"><ElInput v-model="containerForm.unit_price" inputmode="decimal" placeholder="例如 15.89" :disabled="saving"><template #append>{{ version.currency_code }}</template></ElInput></ElFormItem>
        </ElForm>
        <div class="container-preview"><b>装柜数量预估</b><div><span>单箱体积&nbsp; {{ line.packaging?.carton_cbm || '—' }} m³</span><span>每箱数量&nbsp; {{ line.packaging?.pieces_per_carton || '—' }} {{ line.unit_code }}</span><strong>{{ containerPreview ? `${containerPreview.cartons} CTN / ${containerPreview.quantity} ${line.unit_code}` : '— CTN / — PCS' }}</strong></div><small>ⓘ 填写可用容积和装载系数后显示预计数量。</small></div>
        <template #footer><ElButton :disabled="saving" @click="containerDialogVisible = false">取消</ElButton><ElButton class="black-button" :loading="saving" @click="saveContainerTier">保存装柜配置</ElButton></template>
      </AppWindowDialog>
    </template>
    <ElResult v-else-if="errorMessage" icon="error" title="包装配置加载失败" :sub-title="errorMessage"><template #extra><ElButton class="black-button" @click="loadPage">重新加载</ElButton><ElButton @click="backToEditor">返回报价编辑</ElButton></template></ElResult>
  </section>
</template>

<style scoped lang="scss">
.quotation-packaging-page { max-width:1600px; min-width:0; margin:0 auto; color:#1f2329; --el-color-primary:#18181b; }.page-header { display:flex; align-items:center; justify-content:space-between; gap:24px; min-height:64px; margin-bottom:12px; }.back-link { display:flex; align-items:center; gap:4px; border:0; padding:0; color:#18181b; background:transparent; font-size:12px; cursor:pointer; }.title-row { display:flex; align-items:center; gap:10px; margin-top:5px; }.title-row h1 { margin:0; font-size:24px; line-height:30px; }.page-header p { margin:4px 0 0; color:#52525b; font-size:12px; }.header-actions { display:flex; align-items:center; gap:8px; }.header-actions :deep(.el-button) { width:96px; height:32px; }.header-actions .wide-cancel { display:none; width:auto; padding:0 4px; }.black-button { color:#fff!important; border-color:#18181b!important; background:#18181b!important; }.black-button:disabled,.black-button.is-disabled { color:#a8abb2!important; border-color:#e4e7ed!important; background:#f4f4f5!important; }.configuration-steps { display:grid; grid-template-columns:repeat(4,1fr); height:40px; margin-bottom:12px; overflow:hidden; border:1px solid #e4e4e7; border-radius:8px; background:#fff; }.configuration-steps b { display:grid; place-items:center; color:#52525b; font-size:12px; font-weight:500; }.configuration-steps .step-index,.configuration-steps small { display:none; }.configuration-steps .step-copy { display:contents; }.configuration-steps .is-complete { color:#67c23a; }.configuration-steps .is-current { color:#18181b; font-weight:700; }.page-layout { display:grid; grid-template-columns:minmax(0,2.14fr) minmax(340px,1fr); gap:16px; }.page-main { display:grid; align-content:start; gap:12px; min-width:0; }.product-strip { display:flex; align-items:center; gap:16px; min-height:84px; padding:12px 16px; border:1px solid #e4e4e7; border-radius:8px; background:#fff; }.product-icon { display:grid; width:52px; height:52px; flex:none; place-items:center; border-radius:8px; color:#52525b; background:#f7f7f8; font-size:24px; }.product-strip > div:not(.line-nav) { display:grid; flex:1; gap:3px; min-width:0; }.product-strip > div:not(.line-nav) b { font-size:16px; }.product-strip small { overflow:hidden; color:#52525b; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }.line-nav { display:flex; flex:none; gap:8px; }.product-strip :deep(.el-button) { width:80px; height:32px; }.detail-card,.summary-card { border:1px solid #e4e4e7; border-radius:8px; box-shadow:none; }.detail-card :deep(.el-card__header) { min-height:48px; padding:0 16px; }.detail-card :deep(.el-card__body) { padding:14px 16px; }.card-title { display:flex; align-items:center; gap:12px; min-height:47px; }.card-title b { font-size:16px; }.card-title span { flex:1; color:#52525b; font-size:11px; }.card-title :deep(.el-tag) { margin-left:auto; }.specification-grid { display:grid; grid-template-columns:minmax(0,1.6fr) minmax(160px,.8fr) minmax(0,1fr); gap:16px; }.specification-grid label { display:grid; gap:5px; min-width:0; color:#52525b; font-size:12px; }.packaging-form :deep(.el-form-item) { margin-bottom:0; }.packaging-form :deep(.el-form-item__label),.container-dialog-form :deep(.el-form-item__label) { padding-bottom:4px; color:#52525b; font-size:12px; }.dimension-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px 16px; }.formula { margin:12px 0 0; color:#18181b; font-size:12px; }.tier-toolbar { display:flex; justify-content:flex-end; gap:8px; margin-bottom:14px; }.detail-card :deep(.el-table__header th) { height:34px; color:#52525b; background:#fff; }.detail-card :deep(.el-table__body td) { height:42px; }.override-note { margin-top:12px; }.summary-column { min-width:0; }.summary-card { min-height:520px; }.summary-card :deep(.el-card__header) { min-height:54px; padding:0 16px; }.summary-card :deep(.el-card__body) { display:grid; gap:14px; padding:16px; }.summary-title { display:flex; align-items:center; justify-content:space-between; min-height:53px; }.summary-title b { font-size:18px; }.summary-line { position:relative; display:grid; gap:5px; padding:12px 14px; border:1px solid #e4e4e7; border-radius:6px; background:#f7f7f8; }.summary-line small { color:#52525b; }.summary-line strong { font-size:15px; }.summary-line > b { position:absolute; right:14px; bottom:12px; font-size:13px; }.summary-card p { display:flex; justify-content:space-between; gap:8px; margin:0; color:#52525b; font-size:13px; }.summary-card p b { color:#18181b; font-weight:500; text-align:right; }.summary-card h3 { margin:8px 0 0; font-size:15px; }.summary-card .validation { justify-content:flex-start; align-items:center; color:#3f3f46; }.summary-card .validation :deep(.el-icon) { color:#67c23a; }.summary-card .validation.warning :deep(.el-icon) { color:#e6a23c; }.summary-card :deep(.el-alert) { margin-top:6px; }.summary-actions { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:6px; }.summary-actions :deep(.el-button) { height:32px; margin:0; }.summary-footnote { justify-self:center; color:#52525b; font-size:12px; text-align:center; }.dialog-subtitle { margin:0 0 12px; color:#52525b; font-size:13px; }.container-dialog-form { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:0 14px; margin-top:16px; }.container-dialog-form :deep(.el-form-item) { margin-bottom:0; }.container-preview { display:grid; gap:8px; margin-top:16px; padding:14px; border:1px solid #bfdbfe; border-radius:8px; background:#eff6ff; }.container-preview > div { display:flex; flex-wrap:wrap; gap:12px 20px; color:#52525b; font-size:12px; }.container-preview strong { color:#1677ff; }
@media (min-width:1700px) { .header-actions .wide-cancel { display:inline-flex; }.configuration-steps { height:64px; }.configuration-steps b { display:flex; align-items:center; justify-content:flex-start; gap:10px; padding-left:24px; }.configuration-steps .step-index { display:grid; width:28px; height:28px; flex:none; place-items:center; border:1px solid #d4d4d8; border-radius:50%; color:#52525b; background:#fafafa; font-weight:500; }.configuration-steps .step-copy { display:grid; gap:2px; }.configuration-steps .step-copy small { display:block; color:#71717a; font-size:11px; font-weight:400; }.configuration-steps .is-complete .step-index,.configuration-steps .is-current .step-index { border-color:#18181b; color:#fff; background:#18181b; }.configuration-steps .is-complete .step-copy { color:#18181b; }.configuration-steps .is-complete .step-copy small { color:#67c23a; }.configuration-steps .compact-check { display:none; } }
@media (max-width:1200px) { .page-layout { grid-template-columns:minmax(0,1fr) 330px; }.dimension-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@media (max-width:900px) { .page-header { align-items:flex-start; flex-direction:column; }.page-layout { grid-template-columns:1fr; }.page-main :deep(.el-table) { min-width:700px; }.page-main :deep(.el-table__inner-wrapper) { overflow-x:auto; } }
@media (max-width:620px) { .title-row h1 { font-size:20px; }.configuration-steps { grid-template-columns:repeat(2,1fr); height:72px; }.product-strip { align-items:flex-start; flex-wrap:wrap; }.dimension-grid,.container-dialog-form,.specification-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.tier-toolbar { align-items:stretch; flex-direction:column; }.header-actions { width:100%; }.header-actions :deep(.el-button) { flex:1; }.summary-actions { grid-template-columns:1fr; } }

/* QUO-V2-06 至 QUO-V2-10 包装与装柜配置 */
.quotation-packaging-page { max-width: none; min-width: 1280px; margin: 0; color: #1f1d18; --el-color-primary: #c84e28; font-family: 'Noto Sans SC','Microsoft YaHei',sans-serif; }
.page-header { min-height: 102px; align-items: flex-start; margin: 0; }
.back-link { color: #c84e28; }
.title-row { gap: 28px; margin-top: 14px; }
.title-row h1 { font-family: 'Noto Serif SC','STSong',serif; font-size: 36px; font-weight: 600; line-height: 46px; }
.title-row :deep(.el-tag) { min-width: 72px; border: 0; border-radius: 999px; color: #5e5d59; background: #f0eee6; }
.page-header p { color: #6f6a61; font-size: 12px; }
.header-actions { padding-top: 20px; }
.packaging-saved { display: flex; align-items: center; gap: 8px; margin-right: 20px; color: #4f7d4b; font-size: 14px; }
.packaging-saved :deep(.el-icon) { display: grid; width: 24px; height: 24px; place-items: center; border-radius: 50%; background: #e8f0e2; }
.header-actions :deep(.el-button) { width: 184px; height: 44px; margin: 0; border-radius: 5px; font-size: 15px; }
.black-button { color: #fff!important; border-color: #c84e28!important; background: #c84e28!important; }
.black-button:hover { border-color: #b94423!important; background: #b94423!important; }
.black-button.is-disabled,.black-button:disabled { color: #aaa49b!important; border-color: #ece6db!important; background: #eee8dd!important; }
.configuration-steps { display: none; }
.page-layout { grid-template-columns: minmax(0,1fr) 450px; gap: 16px; }
.page-main { gap: 16px; }
.product-strip { min-height: 132px; padding: 20px; border-color: #ddd6c9; border-radius: 5px; background: #fcfbf7; }
.product-icon { width: 88px; height: 88px; border-radius: 8px; color: #968f84; background: #f4f0e8; font-size: 34px; }
.product-strip > div:not(.line-nav) { gap: 5px; }
.product-strip > div:not(.line-nav) b { font-size: 18px; }
.product-strip small { color: #6f6a61; font-size: 14px; }
.product-strip :deep(.el-tag) { align-self: center; margin-left: auto; border: 0; border-radius: 999px; color: #4f7d4b; background: #e8f0e2; }
.line-nav { align-items: center; }
.product-strip :deep(.el-button) { width: 136px; height: 44px; border-color: #ddd6c9; border-radius: 5px; background: #fcfbf7; }
.detail-card,.summary-card { border-color: #ddd6c9; border-radius: 5px; background: #fcfbf7; }
.detail-card :deep(.el-card__header) { min-height: 62px; padding: 0 20px; border-bottom: 0; }
.detail-card :deep(.el-card__body) { padding: 0 20px 22px; }
.card-title { min-height: 62px; gap: 18px; }
.card-title b { font-size: 18px; }
.card-title span { color: #6f6a61; font-size: 13px; }
.card-title :deep(.el-button) { min-width: 220px; height: 44px; margin-left: auto; border-radius: 5px; }
.packaging-form :deep(.el-form-item__label),.container-dialog-form :deep(.el-form-item__label) { padding-bottom: 7px; color: #1f1d18; font-size: 13px; }
.dimension-grid { gap: 22px 24px; }
.dimension-grid :deep(.el-input__wrapper),.dimension-grid :deep(.el-input-group__append) { min-height: 44px; border-radius: 4px; background: #fffefb; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.dimension-grid :deep(.el-input-group__append) { color: #6f6a61; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.dimension-grid :deep(.is-disabled .el-input__wrapper) { background: #f1ede5; }
.formula { min-height: 44px; display: flex; align-items: center; margin: 22px 0 0; padding: 0 16px; color: #6f6a61; background: #f6f2ea; font-size: 12px; }
.detail-card :deep(.el-table) { --el-table-border-color: #e7e0d5; --el-table-header-bg-color: #efe8dd; color: #1f1d18; background: #fcfbf7; }
.detail-card :deep(.el-table__header th) { height: 44px; color: #6f6a61; background: #efe8dd; font-weight: 500; }
.detail-card :deep(.el-table__body td) { height: 52px; background: #fcfbf7; }
.tier-footnote { margin: 14px 0 0; color: #968f84; font-size: 12px; }
.summary-card { min-height: 854px; }
.summary-card :deep(.el-card__header) { min-height: 72px; padding: 0 24px; border-bottom: 0; }
.summary-card :deep(.el-card__body) { gap: 18px; padding: 0 24px 24px; }
.summary-title { min-height: 72px; }
.summary-title b { font-family: 'Noto Serif SC','STSong',serif; font-size: 22px; }
.summary-title :deep(.el-tag) { min-width: 96px; border: 0; border-radius: 999px; color: #b8781e; background: #faeedb; }
.summary-line { min-height: 104px; padding: 0 0 20px; border: 0; border-bottom: 1px solid #ddd6c9; border-radius: 0; background: transparent; }
.summary-line small { color: #6f6a61; font-size: 13px; }
.summary-line strong { font-size: 17px; }
.summary-line > b { right: 0; bottom: 20px; font-size: 14px; }
.summary-card h3 { margin: 10px 0 0; font-family: 'Noto Serif SC','STSong',serif; font-size: 18px; }
.summary-card p { color: #6f6a61; font-size: 14px; }
.summary-card p b { color: #1f1d18; }
.summary-card .validation { font-size: 13px; }
.summary-card :deep(.el-alert) { min-height: 64px; border: 0; color: #b8781e; background: #faeedb; }
.summary-actions { display: block; margin-top: 6px; }
.summary-actions :deep(.el-button) { width: 100%; height: 50px; font-size: 16px; }
.summary-footnote { margin-top: -6px; color: #968f84; }
.container-preview { border-color: #e7c28e; border-radius: 5px; background: #faeedb; }
.container-preview strong { color: #b8781e; }
:global(.quotation-packaging-page .el-dialog) { border-radius: 6px; background: #fcfbf7; }
:global(.quotation-packaging-page .el-dialog__title) { font-family: 'Noto Serif SC','STSong',serif; font-size: 26px; }
:global(.quotation-container-dialog .el-dialog__header) { margin: 0; padding: 32px 32px 0; }
:global(.quotation-container-dialog .el-dialog__body) { padding: 8px 32px 18px; }
:global(.quotation-container-dialog .el-dialog__footer) { padding: 20px 32px 30px; border-top: 1px solid #ddd6c9; }
:global(.quotation-container-dialog .el-dialog__footer .el-button) { min-width: 106px; height: 44px; border-radius: 4px; }
.quotation-container-dialog .dialog-subtitle { margin: 0 0 22px; color: #6f6a61; }
.container-product-snapshot { display: flex; align-items: center; gap: 18px; min-height: 100px; box-sizing: border-box; padding: 18px 20px; border: 1px solid #ddd6c9; border-radius: 5px; background: #fffefb; }
.container-product-icon { display: grid; width: 60px; height: 60px; flex: none; place-items: center; border-radius: 9px; color: #968f84; background: #f4f0e8; font-size: 30px; }
.container-product-snapshot > div { display: grid; flex: 1; gap: 5px; }
.container-product-snapshot b { font-size: 18px; }
.container-product-snapshot small { color: #6f6a61; font-size: 13px; }
.container-product-snapshot :deep(.el-tag) { border: 0; color: #4f7d4b; background: #e8f0e2; }
.quotation-container-dialog .container-dialog-form { grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 24px; margin-top: 24px; }
.quotation-container-dialog .container-dialog-form :deep(.el-form-item) { margin-bottom: 18px; }
.quotation-container-dialog .container-dialog-form :deep(.el-input__wrapper),.quotation-container-dialog .container-dialog-form :deep(.el-input-group__append) { min-height: 44px; border-radius: 4px; background: #fffefb; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.quotation-container-dialog .container-preview { gap: 16px; margin-top: 0; padding: 24px; border: 0; border-radius: 5px; color: #1f1d18; background: #f3ede3; }
.quotation-container-dialog .container-preview > b { font-family: 'Noto Serif SC','STSong',serif; font-size: 18px; }
.quotation-container-dialog .container-preview > div { display: grid; grid-template-columns: 1fr 1fr; gap: 18px 30px; color: #1f1d18; font-size: 14px; }
.quotation-container-dialog .container-preview strong { grid-column: 1 / -1; padding-top: 16px; border-top: 1px solid #ddd6c9; color: #1f1d18; font-size: 20px; }
.quotation-container-dialog .container-preview small { color: #6f6a61; font-size: 12px; }
.quotation-packaging-page .detail-card :deep(.el-table__body-wrapper td.tier-row-action > .cell) {
  padding-right: 8px !important;
  padding-left: 8px !important;
}
</style>
