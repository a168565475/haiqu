<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { CSSProperties } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import { fetchWageScheme } from '@/api/workshopReporting'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { WageScheme } from '@/types/workshopReporting'
import { compactDecimal } from '@/utils/compactDecimal'
import { formatWageMoney } from '@/utils/wageMoney'

const props = defineProps<{
  modelValue: boolean
  schemeId: string | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const router = useRouter()
const auth = useAuthStore()
const scheme = ref<WageScheme | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const linesSectionRef = ref<HTMLElement | null>(null)
const tableMaxHeight = ref(560)
let requestSequence = 0
let linesSectionObserver: ResizeObserver | null = null

const tableCssVariables = {
  '--el-table-bg-color': 'var(--erp-table-body-fill)',
  '--el-table-tr-bg-color': 'var(--erp-table-body-fill)',
  '--el-table-header-bg-color': 'var(--erp-table-header-fill)',
  '--el-table-border-color': 'var(--erp-table-grid)',
  '--el-table-row-hover-bg-color': 'var(--erp-color-hover)',
  '--el-table-current-row-bg-color': 'var(--erp-color-selected)',
} as CSSProperties
const tableHeaderCellStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: '44px',
  padding: '0',
  color: 'var(--erp-table-header-text)',
  background: 'var(--erp-table-header-fill)',
  fontSize: '11px',
  fontWeight: '400',
  lineHeight: '16px',
}
const tableBodyCellStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: '36px',
  padding: '0',
  color: 'var(--erp-table-text)',
  background: 'var(--erp-table-body-fill)',
  fontSize: '12px',
  lineHeight: '18px',
}
const tableRowStyle: CSSProperties = { height: '36px' }

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})

const canCreateChange = computed(() => scheme.value?.status === 'APPROVED'
  && Boolean(scheme.value.can_create_change) && Boolean(
  auth.user?.is_superuser || (
    auth.hasPermission('workshop_reporting.change_wagescheme')
    && auth.hasPermission('workshop_reporting.submit_wagescheme')
  ),
  ))

function schemeStatusClass(status: string) {
  return ({
    APPROVED: 'is-success',
    PENDING_APPROVAL: 'is-warning',
    RETURNED: 'is-danger',
    SUPERSEDED: 'is-neutral',
    DRAFT: 'is-neutral',
  } as Record<string, string>)[status] || 'is-neutral'
}

function errorText(error: unknown) {
  return (error as { response?: { data?: { error?: { message?: string } } } })
    ?.response?.data?.error?.message || '工价详情加载失败。'
}

function updateTableMaxHeight() {
  const sectionHeight = linesSectionRef.value?.clientHeight
  if (!sectionHeight) return
  tableMaxHeight.value = Math.max(152, Math.floor(sectionHeight - 34))
}

async function openChange() {
  if (!scheme.value || !canCreateChange.value) return
  try {
    await router.push({
      name: 'wage-scheme-change',
      params: { schemeId: scheme.value.id },
    })
    visible.value = false
  } catch {
    ElMessage.error('变更页面打开失败，请稍后重试。')
  }
}

async function load() {
  if (!props.schemeId) return
  const current = ++requestSequence
  scheme.value = null
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchWageScheme(props.schemeId)
    if (current !== requestSequence) return
    scheme.value = result.data
  } catch (error) {
    if (current !== requestSequence) return
    scheme.value = null
    errorMessage.value = errorText(error)
    ElMessage.error(errorMessage.value)
  } finally {
    if (current === requestSequence) loading.value = false
  }
}

watch(
  [() => props.modelValue, () => props.schemeId],
  ([isVisible, schemeId]) => {
    if (isVisible && schemeId) {
      void load()
      return
    }
    requestSequence += 1
    loading.value = false
    errorMessage.value = ''
    scheme.value = null
  },
  { immediate: true },
)

watch(linesSectionRef, (currentSection, previousSection) => {
  if (previousSection) linesSectionObserver?.unobserve(previousSection)
  if (!currentSection) return
  if (typeof ResizeObserver !== 'undefined') {
    linesSectionObserver ??= new ResizeObserver(updateTableMaxHeight)
    linesSectionObserver.observe(currentSection)
  }
  void nextTick(updateTableMaxHeight)
})

onBeforeUnmount(() => linesSectionObserver?.disconnect())
</script>

<template>
  <AppWindowDialog
    v-model="visible"
    class="wage-detail-dialog"
    title="工价详情"
    :width="1540"
    :height="850"
    :min-width="920"
    :min-height="560"
    destroy-on-close
    :close-on-click-modal="false"
    data-testid="wage-scheme-detail-dialog"
  >
    <template #title>
      <div class="wage-detail-dialog__heading">
        <strong>工价详情</strong>
        <template v-if="scheme">
          <span>{{ scheme.scheme_number }}</span>
          <span class="wage-status-tag" :class="schemeStatusClass(scheme.status)">
            {{ scheme.status_display }}
          </span>
        </template>
      </div>
    </template>

    <div v-loading="loading" class="wage-detail-dialog__content">
      <ElAlert
        v-if="errorMessage"
        type="error"
        show-icon
        :closable="false"
        :title="errorMessage"
      >
        <ElButton @click="load">重试</ElButton>
      </ElAlert>

      <template v-else-if="scheme">
        <section ref="linesSectionRef" class="wage-detail-dialog__section wage-detail-dialog__section--lines">
          <h3>工价明细</h3>
          <ElTable
            class="wage-detail-dialog__table"
            :data="scheme.lines"
            :style="tableCssVariables"
            :header-cell-style="tableHeaderCellStyle"
            :cell-style="tableBodyCellStyle"
            :row-style="tableRowStyle"
            border
            :max-height="tableMaxHeight"
            empty-text="暂无工价明细"
          >
            <ElTableColumn prop="display_name" label="名称 / 部位" min-width="150" show-overflow-tooltip />
            <ElTableColumn prop="operation_name" label="申报工序" min-width="100" show-overflow-tooltip />
            <ElTableColumn v-if="scheme.scope_craft?.plan_category === 'SEWING'" prop="counting_mode_display" label="计数方式" width="82" align="center" />
            <ElTableColumn prop="production_description" label="制作工序描述" min-width="170" show-overflow-tooltip>
              <template #default="{ row }">{{ row.production_description || '—' }}</template>
            </ElTableColumn>
            <ElTableColumn prop="declared_price" label="申报工价" width="88" align="center" class-name="is-money">
              <template #default="{ row }">{{ formatWageMoney(row.declared_price) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="required_quantity" label="需完成次数" width="110" align="right"><template #default="{ row }">{{ compactDecimal(row.required_quantity) }}</template></ElTableColumn>
            <ElTableColumn prop="completed_quantity" label="已完成次数" width="110" align="right"><template #default="{ row }">{{ compactDecimal(row.completed_quantity) }}</template></ElTableColumn>
            <ElTableColumn prop="completed_amount" label="已完成金额" width="120" align="right" class-name="is-money">
              <template #default="{ row }">{{ formatWageMoney(row.completed_amount) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="estimated_amount" label="金额总计" width="120" align="right" class-name="is-money">
              <template #default="{ row }">{{ formatWageMoney(row.estimated_amount) }}</template>
            </ElTableColumn>
            <ElTableColumn label="状态" width="72" align="center">
              <template #default="{ row }">
                <span class="wage-status-tag" :class="row.status === 'ACTIVE' ? 'is-success' : 'is-danger'">
                  {{ row.status === 'ACTIVE' ? '正常' : '作废' }}
                </span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="previous_price" label="以往工价" width="88" align="center" class-name="is-money">
              <template #default="{ row }">{{ formatWageMoney(row.previous_price) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="revised_price" label="修改工价" width="88" align="center" class-name="is-money">
              <template #default="{ row }">{{ formatWageMoney(row.revised_price) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="note" label="备注" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">{{ row.note || '—' }}</template>
            </ElTableColumn>
          </ElTable>
        </section>
      </template>
    </div>

    <template #footer>
      <div class="wage-detail-dialog__footer">
        <ElButton @click="visible = false">关闭</ElButton>
        <ElButton
          v-if="canCreateChange"
          type="primary"
          data-testid="wage-scheme-change-button"
          @click="openChange"
        >
          变更
        </ElButton>
      </div>
    </template>
  </AppWindowDialog>
</template>

<style lang="scss">
@use '@/styles/theme/detail' as detail;

.app-window-dialog.wage-detail-dialog {
  font-family: 'Noto Sans SC Variable', 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  --el-color-primary: var(--erp-color-brand);
  --el-border-color-lighter: var(--erp-color-border-subtle);

  .app-window-dialog__body {
    min-height: 0;
    overflow: hidden;
  }

  .wage-detail-dialog__table {
    --el-table-bg-color: var(--erp-table-body-fill);
    --el-table-tr-bg-color: var(--erp-table-body-fill);
    --el-table-header-bg-color: var(--erp-table-header-fill);
    --el-table-border-color: var(--erp-table-grid);
    --el-table-row-hover-bg-color: var(--erp-color-hover);
    --el-table-current-row-bg-color: var(--erp-color-selected);
    color: var(--erp-table-text);
    font-size: 12px;
  }

  .el-table__header-wrapper th.el-table__cell {
    box-sizing: border-box;
    height: 44px !important;
    padding: 0 !important;
    color: var(--erp-table-header-text) !important;
    background: var(--erp-table-header-fill) !important;
    font-size: 11px !important;
    font-weight: 400 !important;
    line-height: 16px !important;
  }

  .el-table__body tr {
    height: 36px !important;
  }

  .el-table__header-wrapper .cell {
    white-space: nowrap;
  }

  .el-table__body-wrapper td.el-table__cell {
    box-sizing: border-box;
    height: 36px !important;
    padding: 0 !important;
    color: var(--erp-table-text);
    background: var(--erp-table-body-fill);
    font-size: 12px !important;
    line-height: 18px !important;
  }

  .el-table__cell > .cell {
    padding-right: 16px !important;
    padding-left: 16px !important;
    line-height: inherit;
  }

  .el-table__body tr:hover > td.el-table__cell {
    background: var(--erp-color-hover) !important;
  }

  .el-table td.is-money .cell {
    color: var(--erp-table-text);
    font-size: 13px;
    font-weight: 600;
    line-height: 20px;
  }
}

.wage-detail-dialog__heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 16px;

  strong {
    flex: none;
    color: var(--erp-color-text-primary);
    font-family: 'Noto Serif SC Variable', 'Noto Serif SC', 'Songti SC', serif;
    font-weight: 600;
  }

  > span {
    color: var(--erp-color-text-regular);
    font-family: 'Noto Sans SC Variable', 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
    font-size: 12px;
  }
}

.wage-detail-dialog__content {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-columns: minmax(0, 1fr);
}

.wage-detail-dialog__section {
  @include detail.inset;
  padding: 14px;
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;

  h3 {
    position: relative;
    flex: none;
    margin: 0 0 10px;
    padding-left: 16px;
    color: var(--erp-color-text-primary);
    font-size: 16px;
    line-height: 24px;

    &::before {
      position: absolute;
      top: 3px;
      bottom: 3px;
      left: 0;
      width: 4px;
      border-radius: 2px;
      background: var(--erp-color-brand);
      content: '';
    }
  }

  .el-table {
    min-height: 0;
  }
}

.wage-detail-dialog__table {
  width: 100%;
  overflow: hidden;
  border-radius: var(--erp-radius-control);
}

.wage-status-tag {
  box-sizing: border-box;
  display: inline-flex;
  min-width: 56px;
  height: 24px;
  align-items: center;
  justify-content: center;
  padding: 0 8px;
  border-radius: 999px;
  color: var(--erp-color-text-inverse) !important;
  font-family: 'Noto Sans SC Variable', 'Noto Sans SC', 'Microsoft YaHei', sans-serif !important;
  font-size: 12px !important;
  font-weight: 500;
  line-height: 18px;
  white-space: nowrap;

  &.is-success { background: var(--erp-tag-success-background); }
  &.is-info { background: var(--erp-tag-info-background); }
  &.is-warning { background: var(--erp-tag-warning-background); }
  &.is-danger { background: var(--erp-tag-danger-background); }
  &.is-neutral { background: var(--erp-tag-neutral-background); }
}

.wage-detail-dialog__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 20px;

  .el-button {
    min-width: 110px;
    margin-left: 0;
    border-radius: 5px;
    font-size: 13px;
    font-weight: 400;
  }

  .el-button--primary {
    min-width: 140px;
  }
}

@media (max-width: 1280px) {
  .app-window-dialog.wage-detail-dialog {
    .app-window-dialog__body { padding: 16px; }
  }
}
</style>
