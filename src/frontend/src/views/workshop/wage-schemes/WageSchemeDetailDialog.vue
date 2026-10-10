<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { CSSProperties } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import { fetchWageScheme } from '@/api/workshopReporting'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { WageScheme } from '@/types/workshopReporting'
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
  '--el-table-bg-color': '#fcfbf7',
  '--el-table-tr-bg-color': '#fcfbf7',
  '--el-table-header-bg-color': '#f0eadf',
  '--el-table-border-color': '#ddd6c9',
  '--el-table-row-hover-bg-color': '#fff6ea',
  '--el-table-current-row-bg-color': '#fff4e6',
} as CSSProperties
const tableHeaderCellStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: '44px',
  padding: '0',
  color: '#6f6a61',
  background: '#f0eadf',
  fontSize: '11px',
  fontWeight: '400',
  lineHeight: '16px',
}
const tableBodyCellStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: '36px',
  padding: '0',
  color: '#4d4c48',
  background: '#fcfbf7',
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

function eventStatusClass(action: string) {
  return ({
    APPROVED: 'is-success',
    SUBMITTED: 'is-info',
    RETURNED: 'is-danger',
    CHANGE_CREATED: 'is-warning',
  } as Record<string, string>)[action] || 'is-neutral'
}

function eventTimelineColor(action: string) {
  return ({
    APPROVED: '#4f7d4b',
    SUBMITTED: '#3898ec',
    RETURNED: '#b53333',
    CHANGE_CREATED: '#b8781e',
  } as Record<string, string>)[action] || '#5e5d59'
}

function formatDateTime(value: string) {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 16)
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
            <ElTableColumn label="需完成次数" width="98" align="right"><template #default="{ row }">{{ row.required_quantity ?? '—' }}</template></ElTableColumn>
            <ElTableColumn prop="production_description" label="制作工序描述" min-width="170" show-overflow-tooltip>
              <template #default="{ row }">{{ row.production_description || '—' }}</template>
            </ElTableColumn>
            <ElTableColumn prop="declared_price" label="申报工价" width="88" align="center" class-name="is-money">
              <template #default="{ row }">{{ formatWageMoney(row.declared_price) }}</template>
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

        <section class="wage-detail-dialog__section wage-detail-dialog__section--events">
          <h3>审批记录</h3>
          <ElTimeline v-if="scheme.events.length" class="wage-detail-dialog__approval-list">
            <ElTimelineItem
              v-for="event in scheme.events"
              :key="event.id"
              :color="eventTimelineColor(event.action)"
              :timestamp="formatDateTime(event.created_at)"
              placement="top"
            >
              <article class="wage-detail-dialog__event">
                <header>
                  <span class="wage-status-tag" :class="eventStatusClass(event.action)">
                    {{ event.action_display }}
                  </span>
                  <strong>{{ event.actor || '—' }}</strong>
                </header>
                <p>{{ event.comment || '—' }}</p>
              </article>
            </ElTimelineItem>
          </ElTimeline>
          <ElEmpty v-else class="wage-detail-dialog__events-empty" :image-size="72" description="暂无审批记录" />
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
.app-window-dialog.wage-detail-dialog {
  font-family: 'Noto Sans SC Variable', 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  --el-color-primary: #c84e28;
  --el-border-color-lighter: #ddd6c9;

  .app-window-dialog__body {
    min-height: 0;
    overflow: hidden;
  }

  .wage-detail-dialog__table {
    --el-table-bg-color: #fcfbf7;
    --el-table-tr-bg-color: #fcfbf7;
    --el-table-header-bg-color: #f0eadf;
    --el-table-border-color: #ddd6c9;
    --el-table-row-hover-bg-color: #fff6ea;
    --el-table-current-row-bg-color: #fff4e6;
    color: #4d4c48;
    font-size: 12px;
  }

  .el-table__header-wrapper th.el-table__cell {
    box-sizing: border-box;
    height: 44px !important;
    padding: 0 !important;
    color: #6f6a61 !important;
    background: #f0eadf !important;
    font-size: 11px !important;
    font-weight: 400 !important;
    line-height: 16px !important;
  }

  .el-table__body tr {
    height: 36px !important;
  }

  .el-table__body-wrapper td.el-table__cell {
    box-sizing: border-box;
    height: 36px !important;
    padding: 0 !important;
    color: #4d4c48;
    background: #fcfbf7;
    font-size: 12px !important;
    line-height: 18px !important;
  }

  .el-table__cell > .cell {
    padding-right: 16px !important;
    padding-left: 16px !important;
    line-height: inherit;
  }

  .el-table__body tr:hover > td.el-table__cell {
    background: #fff6ea !important;
  }

  .el-table td.is-money .cell {
    color: #1f1d18;
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
    color: #1f1d18;
    font-family: 'Noto Serif SC Variable', 'Noto Serif SC', 'Songti SC', serif;
    font-weight: 600;
  }

  > span {
    color: #4d4c48;
    font-family: 'Noto Sans SC Variable', 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
    font-size: 12px;
  }
}

.wage-detail-dialog__content {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 24px;
}

.wage-detail-dialog__section {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;

  h3 {
    position: relative;
    flex: none;
    margin: 0 0 10px;
    padding-left: 16px;
    color: #1f1d18;
    font-size: 16px;
    line-height: 24px;

    &::before {
      position: absolute;
      top: 3px;
      bottom: 3px;
      left: 0;
      width: 4px;
      border-radius: 2px;
      background: #c84e28;
      content: '';
    }
  }

  .el-table {
    min-height: 0;
  }
}

.wage-detail-dialog__section--events {
  padding-left: 24px;
  border-left: 1px solid #ddd6c9;
}

.wage-detail-dialog__approval-list {
  min-height: 0;
  margin: 0;
  padding: 6px 4px 0 8px;
  overflow-y: auto;

  .el-timeline-item {
    padding-bottom: 24px;
  }

  .el-timeline-item__timestamp {
    margin-bottom: 8px;
    color: #968f84;
    font-size: 11px;
    line-height: 16px;
  }

  .el-timeline-item__tail {
    border-left-color: #ddd6c9;
  }
}

.wage-detail-dialog__event {
  padding: 14px 16px;
  border: 1px solid #ddd6c9;
  border-radius: 5px;
  background: #fcfbf7;

  header {
    display: flex;
    align-items: center;
    gap: 10px;

    strong {
      min-width: 0;
      overflow: hidden;
      color: #1f1d18;
      font-size: 13px;
      font-weight: 600;
      line-height: 20px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  p {
    margin: 10px 0 0;
    color: #4d4c48;
    font-size: 12px;
    line-height: 20px;
    overflow-wrap: anywhere;
  }
}

.wage-detail-dialog__events-empty {
  min-height: 0;
  flex: 1;
}

.wage-detail-dialog__table {
  width: 100%;
  overflow: hidden;
  border-radius: 5px;
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
  color: #faf9f5 !important;
  font-family: 'Noto Sans SC Variable', 'Noto Sans SC', 'Microsoft YaHei', sans-serif !important;
  font-size: 12px !important;
  font-weight: 500;
  line-height: 18px;
  white-space: nowrap;

  &.is-success { background: #4f7d4b; }
  &.is-info { background: #3898ec; }
  &.is-warning { background: #b8781e; }
  &.is-danger { background: #b53333; }
  &.is-neutral { background: #5e5d59; }
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

  .wage-detail-dialog__content {
    grid-template-columns: minmax(0, 1fr) 280px;
    gap: 16px;
  }

  .wage-detail-dialog__section--events {
    padding-left: 16px;
  }
}
</style>
