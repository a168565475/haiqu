<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'

import { fetchMaterialTracking, fetchMaterialTrackingDetail, materialTrackingBomFileUrl } from '@/api/materialTracking'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import ProtectedAttachmentLink from '@/components/common/ProtectedAttachmentLink.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import type { MaterialTrackingDetail, MaterialTrackingRow, TrackingStage } from '@/types/materialTracking'
import { workbenchErrorMessage } from '@/utils/workbench'

type TableStage = TrackingStage | 'coating_factories'
type DetailSection = TableStage | 'packaging_requirements'

const columns: Record<DetailSection, string> = {
  steel_purchase: '钢管下单日',
  metal_issue: '管材仓库出库日',
  metal_completion: '最近金工合格完成日',
  coating_dispatch: '最近交喷塑日',
  coating_factories: '喷塑厂家',
  coating_receipt: '最近喷塑回厂日',
  fabric_purchase: '布料下单日',
  fabric_arrival: '布料到齐日',
  sewn_receipt: '最近布面入库日',
  plastic_purchase: '塑料件下单日',
  plastic_receipt: '塑料件最近入库日',
  hardware_purchase: '五金下单日',
  hardware_receipt: '五金最近入库日',
  packaging_purchase: '包材下单日',
  packaging_receipt: '包材最近入库日',
  assembly_first: '首次装配报工日期／线号',
  assembly_completion: '装配完工登记日',
  finished_receipt: '成品已入库数量',
  packaging_requirements: '包装要求',
}

const groups: { label: string; columns: TableStage[] }[] = [
  { label: '管材与喷塑', columns: ['steel_purchase', 'metal_issue', 'metal_completion', 'coating_dispatch', 'coating_factories', 'coating_receipt'] },
  { label: '布料与配件', columns: [
    'fabric_purchase', 'fabric_arrival', 'sewn_receipt', 'plastic_purchase', 'plastic_receipt',
    'hardware_purchase', 'hardware_receipt', 'packaging_purchase', 'packaging_receipt',
  ] },
  { label: '装配与成品', columns: ['assembly_first', 'assembly_completion', 'finished_receipt'] },
]

const search = ref('')
const taskNumber = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const rows = ref<MaterialTrackingRow[]>([])
const loading = ref(false)
const errorMessage = ref('')
let listRequest: AbortController | undefined

const selected = ref<{ row: MaterialTrackingRow; section: DetailSection } | null>(null)
const detail = ref<MaterialTrackingDetail | null>(null)
const detailError = ref('')
const detailBatches = computed(() => {
  if (!selected.value || !detail.value) return []
  const { section } = selected.value
  return detail.value.batches.filter(batch => section === 'coating_factories'
    ? batch.kind === 'coating_dispatch' || batch.kind === 'coating_receipt'
    : batch.kind === section)
})
let detailRequest: AbortController | undefined

function resetDetail() {
  detailRequest?.abort()
  selected.value = null
  detail.value = null
  detailError.value = ''
}

async function load() {
  listRequest?.abort()
  resetDetail()
  const request = new AbortController()
  listRequest = request
  loading.value = true
  errorMessage.value = ''
  rows.value = []
  try {
    const result = await fetchMaterialTracking({
      task_number: taskNumber.value, page: page.value, page_size: pageSize.value,
    }, request.signal)
    if (request.signal.aborted) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (request.signal.aborted) return
    total.value = 0
    errorMessage.value = workbenchErrorMessage(error, '加载材料跟踪')
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}

function applySearch() {
  taskNumber.value = search.value.trim()
  page.value = 1
  void load()
}

function resizePage() {
  page.value = 1
  void load()
}

async function openDetail(row: MaterialTrackingRow, section: DetailSection) {
  resetDetail()
  const request = new AbortController()
  detailRequest = request
  selected.value = { row, section }
  try {
    const data = await fetchMaterialTrackingDetail(row.id, request.signal)
    if (!request.signal.aborted) detail.value = data
  } catch (error) {
    if (!request.signal.aborted) detailError.value = workbenchErrorMessage(error, '加载材料跟踪明细')
  }
}

function cellText(row: MaterialTrackingRow, stage: TableStage) {
  if (stage === 'coating_factories') return row.coating_factories.join('、') || '—'
  if (stage === 'finished_receipt') {
    return row.finished_quantities.map(item => [item.quantity, item.unit].filter(Boolean).join(' ')).join(' / ') || '0'
  }
  const { date, note, batch_count } = row.stages[stage]
  if (stage === 'assembly_completion' && !date && batch_count) return '部分工序已完工'
  if (stage === 'assembly_first' && date && row.assembly_lines.length) {
    return `${date} / ${row.assembly_lines.join('、')} 号线`
  }
  return date || note || '—'
}

function hasDetail(row: MaterialTrackingRow, stage: TableStage) {
  if (stage === 'coating_factories') return row.coating_factories.length > 0
  return row.stages[stage].batch_count > 0 || (stage === 'fabric_arrival' && Boolean(row.stages[stage].note))
}

onMounted(load)
onBeforeUnmount(() => {
  listRequest?.abort()
  detailRequest?.abort()
})
</script>

<template>
  <section class="erp-glass-list material-tracking" data-testid="material-tracking">
    <section v-glass-spotlight class="erp-list-filter">
      <header class="erp-list-heading"><h1>材料跟踪</h1></header>
      <form class="erp-list-filters tracking-search" @submit.prevent="applySearch">
        <ElInput
          v-model="search" clearable maxlength="50" aria-label="生产任务单号"
          placeholder="搜索生产任务单号" :prefix-icon="Search" @clear="applySearch"
        />
        <ElButton type="primary" native-type="submit" class="erp-button-motion">查询</ElButton>
      </form>
    </section>

    <section class="erp-list-data">
      <section class="erp-list-table-frame">
        <ElTable
          v-loading="loading" :data="rows" row-key="id" height="100%"
          :empty-text="loading ? '加载中…' : taskNumber ? '未找到该生产任务单的可见产品' : '暂无可见产品'"
        >
          <template v-if="errorMessage" #empty>
            <div role="alert">{{ errorMessage }} <ElButton link type="primary" @click="load">重试</ElButton></div>
          </template>
          <ElTableColumn prop="task_number" label="生产任务单号" width="174" fixed="left" show-overflow-tooltip />
          <ElTableColumn label="产品名称" min-width="175" prop="product_name" show-overflow-tooltip />
          <ElTableColumn label="订单数量" width="110" align="right">
            <template #default="{ row }">{{ row.order_quantity }} {{ row.order_unit }}</template>
          </ElTableColumn>
          <ElTableColumn label="颜色" width="112" show-overflow-tooltip>
            <template #default="{ row }">{{ row.color || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn v-for="group in groups" :key="group.label" :label="group.label">
            <ElTableColumn v-for="stage in group.columns" :key="stage" :label="columns[stage]"
              :width="stage === 'assembly_first' ? 205 : 157" :align="stage === 'finished_receipt' ? 'right' : 'left'">
              <template #default="{ row }">
                <ElButton v-if="hasDetail(row, stage)" link type="primary" class="tracking-cell-link"
                  :aria-label="columns[stage] + ' ' + cellText(row, stage)"
                  :title="stage === 'coating_factories' ? cellText(row, stage) : row.stages[stage].note"
                  @click="openDetail(row, stage)">
                  {{ cellText(row, stage) }}
                </ElButton>
                <span v-else>{{ cellText(row, stage) }}</span>
              </template>
            </ElTableColumn>
          </ElTableColumn>
          <ElTableColumn label="资料">
            <ElTableColumn label="BOM 文件" width="145">
              <template #default="{ row }">
                <template v-if="row.bom">
                  <ProtectedAttachmentLink v-if="row.bom.file_name"
                    :src="materialTrackingBomFileUrl(row.id, row.bom.id)" :filename="row.bom.file_name" download>
                    BOM 源文件
                  </ProtectedAttachmentLink>
                  <RouterLink v-else :to="{ name: 'bom-preview', params: { bomId: row.bom.id } }">BOM 预览</RouterLink>
                </template>
                <span v-else>—</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="包装资料" width="120">
              <template #default="{ row }">
                <ElButton v-if="row.has_packaging_requirements" link type="primary"
                  @click="openDetail(row, 'packaging_requirements')">包装要求</ElButton>
                <span v-else>—</span>
              </template>
            </ElTableColumn>
          </ElTableColumn>
        </ElTable>
      </section>
      <footer class="erp-list-footer">
        <span>共 {{ total }} 条</span>
        <ElPagination v-model:current-page="page" v-model:page-size="pageSize" background
          :page-sizes="[20, 50, 100]" :total="total" layout="sizes, prev, pager, next"
          @current-change="load" @size-change="resizePage" />
      </footer>
    </section>

    <AppWindowDialog
      :model-value="selected !== null"
      :title="selected ? [selected.row.task_number, selected.row.product_name, columns[selected.section]].join(' · ') : ''"
      :width="1100" destroy-on-close @update:model-value="value => { if (!value) resetDetail() }"
    >
      <div v-if="detailError" role="alert">{{ detailError }}</div>
      <div v-else-if="!detail" role="status">正在读取明细…</div>
      <template v-else-if="selected?.section === 'packaging_requirements'">
        <p class="tracking-packaging">{{ detail.packaging_requirements }}</p>
      </template>
      <template v-else>
        <ElTable v-if="selected?.section === 'fabric_arrival' && detail.fabrics.length" :data="detail.fabrics" max-height="240">
          <ElTableColumn label="布料规格" prop="material" min-width="200" show-overflow-tooltip />
          <ElTableColumn label="需求量" width="125" align="right">
            <template #default="{ row }">{{ row.required }} {{ row.unit }}</template>
          </ElTableColumn>
          <ElTableColumn label="累计入库" width="125" align="right">
            <template #default="{ row }">{{ row.total_received }} {{ row.unit }}</template>
          </ElTableColumn>
          <ElTableColumn label="首次到齐日" width="130">
            <template #default="{ row }">{{ row.arrived_on || '未到齐' }}</template>
          </ElTableColumn>
        </ElTable>
        <ElTable :data="detailBatches" empty-text="暂无可核对的批次" max-height="360">
          <ElTableColumn label="业务日期" width="112">
            <template #default="{ row }">{{ row.date || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn v-if="selected?.section === 'coating_factories'" label="环节" width="94">
            <template #default="{ row }">{{ row.kind === 'coating_dispatch' ? '交喷塑' : '喷塑回厂' }}</template>
          </ElTableColumn>
          <ElTableColumn label="原单编号" prop="number" min-width="145" show-overflow-tooltip />
          <ElTableColumn label="厂家／线号" prop="party" min-width="128" show-overflow-tooltip />
          <ElTableColumn label="材料／工序" prop="material" min-width="140" show-overflow-tooltip />
          <ElTableColumn label="数量" width="110" align="right">
            <template #default="{ row }">{{ row.quantity === null ? '—' : [row.quantity, row.unit].filter(Boolean).join(' ') }}</template>
          </ElTableColumn>
          <ElTableColumn label="说明" prop="note" min-width="110" show-overflow-tooltip />
        </ElTable>
      </template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
.tracking-search :deep(.el-input) { width: min(100%, 250px); }
.tracking-packaging { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
.tracking-cell-link { max-width: 100%; }
.tracking-cell-link :deep(span) { overflow: hidden; text-overflow: ellipsis; }
</style>
