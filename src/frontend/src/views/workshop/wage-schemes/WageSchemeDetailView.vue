<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { approveWageScheme, fetchWageScheme, returnWageScheme, submitWageScheme } from '@/api/workshopReporting'
import { useAuthStore } from '@/stores/auth'
import type { WageScheme } from '@/types/workshopReporting'
import { compactDecimal } from '@/utils/compactDecimal'
import { formatWageMoney } from '@/utils/wageMoney'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const scheme = ref<WageScheme | null>(null)
const etag = ref('')
const loading = ref(false)
const acting = ref(false)

const canApprove = () => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.approve_wagescheme')
const canChange = () => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.change_wagescheme')
const canEditDraft = () => canChange() && (
  auth.user?.is_superuser || scheme.value?.created_by_id === auth.user?.employee?.id
  || auth.user?.effective_access?.actions['workshop_reporting.change_wagescheme']?.scopes
    .some(scope => scope === 'MODULE' || scope === 'ALL')
)
const canSubmit = () => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.submit_wagescheme')
const schemeType = computed(() => scheme.value?.parent_scheme ? '变更' : '新增')
const submittedAt = computed(() => scheme.value?.events
  .filter(event => event.action === 'SUBMITTED')
  .map(event => event.created_at)
  .sort()
  .at(-1))

const statusClass = (status: string) => ({
  APPROVED: 'is-success',
  PENDING_APPROVAL: 'is-warning',
  RETURNED: 'is-danger',
  DRAFT: 'is-neutral',
  SUPERSEDED: 'is-neutral',
}[status] || 'is-neutral')

const formatDateTime = (value?: string) => value ? value.replace('T', ' ').slice(0, 16) : '—'
const errorText = (error: unknown) => (
  error as { response?: { data?: { error?: { message?: string } } } }
)?.response?.data?.error?.message || '操作失败。'

async function load() {
  loading.value = true
  try {
    const result = await fetchWageScheme(String(route.params.schemeId))
    scheme.value = result.data
    etag.value = result.etag
  } catch (error) {
    ElMessage.error(errorText(error))
  } finally {
    loading.value = false
  }
}

async function submit() {
  acting.value = true
  try {
    const result = await submitWageScheme(String(route.params.schemeId), etag.value)
    scheme.value = result.data
    etag.value = result.etag
    ElMessage.success('已送交厂长审批。')
  } catch (error) {
    ElMessage.error(errorText(error))
  } finally {
    acting.value = false
  }
}

async function approve() {
  try {
    await ElMessageBox.confirm(
      '确认批准当前工价方案？系统将自动确定生效日期。',
      '批准工价方案',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        customClass: 'wr-confirm-message-box',
        closeOnClickModal: false,
      },
    )
    acting.value = true
    const result = await approveWageScheme(String(route.params.schemeId), etag.value)
    scheme.value = result.data
    etag.value = result.etag
    ElMessage.success('方案已批准。')
    await router.push({ name: 'wage-schemes', query: { detail: result.data.id } })
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorText(error))
  } finally {
    acting.value = false
  }
}

async function returnBack() {
  try {
    const value = await ElMessageBox.prompt('请填写退回原因。', '退回工价方案', {
      inputPattern: /\S{2,}/,
      inputErrorMessage: '至少填写 2 个字符。',
    })
    acting.value = true
    const result = await returnWageScheme(String(route.params.schemeId), etag.value, value.value)
    scheme.value = result.data
    etag.value = result.etag
    ElMessage.success('方案已退回。')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorText(error))
  } finally {
    acting.value = false
  }
}

onMounted(load)
</script>

<template>
  <section v-loading="loading" class="wr-page wr-approval-page" data-testid="wage-scheme-detail">
    <template v-if="scheme">
      <header class="wr-heading wr-approval-heading">
        <div>
          <div class="wr-title-row">
            <h1>工价方案审批</h1>
            <span class="wr-status-tag" :class="statusClass(scheme.status)">{{ scheme.status_display }}</span>
          </div>
          <p>{{ scheme.scheme_number }}</p>
        </div>
        <div>
          <ElButton @click="router.push({ name: 'wage-schemes' })">返回列表</ElButton>
          <ElButton
            v-if="(scheme.status === 'DRAFT' || scheme.status === 'RETURNED') && canEditDraft()"
            @click="router.push({ name: 'wage-scheme-change', params: { schemeId: scheme.id } })"
          >编辑</ElButton>
          <ElButton
            v-if="scheme.can_create_change && canChange() && canSubmit()"
            @click="router.push({ name: 'wage-scheme-change', params: { schemeId: scheme.id } })"
          >变更</ElButton>
          <ElButton
            v-if="(scheme.status === 'DRAFT' || scheme.status === 'RETURNED') && canSubmit()"
            type="primary"
            :loading="acting"
            @click="submit"
          >送审</ElButton>
        </div>
      </header>

      <section class="wr-card wr-approval-card">
        <h2>基本信息</h2>
        <dl class="wr-approval-info">
          <div><dt>生产任务单</dt><dd>{{ scheme.production_task.task_number || '—' }}</dd></div>
          <div><dt>所属产品</dt><dd>{{ [scheme.product.number, scheme.product.name, scheme.product.specification].filter(Boolean).join(' · ') || '—' }}</dd></div>
          <div><dt>生产车间</dt><dd>{{ scheme.workshop.name || '—' }}</dd></div>
          <div><dt>所属工艺</dt><dd>{{ scheme.crafts.map(item => item.name).join('、') || '—' }}</dd></div>
          <div><dt>工序品名</dt><dd>{{ scheme.operation_product_name || '—' }}</dd></div>
          <div><dt>类型</dt><dd>{{ schemeType }}</dd></div>
          <div><dt>申请人</dt><dd>{{ scheme.created_by || '—' }}</dd></div>
          <div><dt>提交时间</dt><dd>{{ formatDateTime(submittedAt) }}</dd></div>
          <div class="is-wide"><dt>备注</dt><dd>{{ scheme.remark || '—' }}</dd></div>
        </dl>
      </section>

      <section class="wr-card wr-approval-card">
        <h2>工价明细</h2>
        <ElTable class="wr-approval-table" :data="scheme.lines" border empty-text="暂无工价明细">
          <ElTableColumn prop="display_name" label="名称 / 部位" min-width="180" show-overflow-tooltip />
          <ElTableColumn prop="operation_name" label="申报工序" min-width="130" show-overflow-tooltip />
          <ElTableColumn v-if="scheme.scope_craft?.plan_category === 'SEWING'" prop="counting_mode_display" label="计数方式" width="100" align="center" />
          <ElTableColumn label="需完成次数" width="112" align="right"><template #default="{ row }">{{ compactDecimal(row.required_quantity) }}</template></ElTableColumn>
          <ElTableColumn prop="production_description" label="制作工序描述" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.production_description || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn prop="declared_price" label="申报工价" width="110" align="center" class-name="wr-money">
            <template #default="{ row }">{{ formatWageMoney(row.declared_price) }}</template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="100" align="center">
            <template #default="{ row }">
              <span class="wr-status-tag" :class="row.status === 'ACTIVE' ? 'is-success' : 'is-danger'">
                {{ row.status === 'ACTIVE' ? '正常' : '作废' }}
              </span>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="previous_price" label="以往工价" width="110" align="center" class-name="wr-money">
            <template #default="{ row }">{{ formatWageMoney(row.previous_price) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="revised_price" label="修改工价" width="110" align="center" class-name="wr-money">
            <template #default="{ row }">{{ formatWageMoney(row.revised_price) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="note" label="备注" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">{{ row.note || '—' }}</template>
          </ElTableColumn>
        </ElTable>
        <footer class="wr-total">工价合计：<strong>{{ formatWageMoney(scheme.declared_total) }}</strong></footer>
      </section>

      <section class="wr-card wr-approval-card wr-approval-events">
        <h2>申请与审批记录</h2>
        <ElTable :data="scheme.events" border empty-text="暂无操作记录">
          <ElTableColumn label="时间" width="180"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></ElTableColumn>
          <ElTableColumn prop="action_display" label="动作" width="120" />
          <ElTableColumn prop="actor" label="操作人" width="150" />
          <ElTableColumn prop="comment" label="意见" min-width="240"><template #default="{ row }">{{ row.comment || '—' }}</template></ElTableColumn>
        </ElTable>
      </section>

      <footer v-if="scheme.status === 'PENDING_APPROVAL' && canApprove()" class="wr-approval-actions">
        <ElButton :loading="acting" @click="returnBack">退回</ElButton>
        <ElButton type="primary" :loading="acting" @click="approve">批准</ElButton>
      </footer>
    </template>
  </section>
</template>

<style lang="scss">
@use '@/styles/workshopReporting.scss';

.wr-approval-page {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 14px;

  &.wr-page > .wr-heading.wr-approval-heading { margin-bottom: 0; }
}

.wr-approval-heading {
  min-height: 64px;
  align-items: center;

  .el-button { min-width: 96px; margin-left: 0; font-size: 13px; font-weight: 400; }
  > div:last-child { gap: 14px; }
}

.wr-approval-card {
  padding: 16px;

  h2 { margin-bottom: 14px; }
}

.wr-approval-info {
  display: grid;
  margin: 0;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-top: 1px solid var(--erp-color-border-subtle);
  border-left: 1px solid var(--erp-color-border);

  > div {
    display: grid;
    min-height: 40px;
    grid-template-columns: 88px minmax(0, 1fr);
    border-right: 1px solid var(--erp-color-border);
    border-bottom: 1px solid var(--erp-color-border-subtle);
  }

  > div.is-wide { grid-column: span 4; }

  dt,
  dd {
    display: flex;
    min-width: 0;
    align-items: center;
    box-sizing: border-box;
    margin: 0;
    padding: 8px 12px;
    font-size: 12px;
    line-height: 20px;
  }

  dt { color: var(--erp-color-text-secondary); background: var(--erp-color-subtle); }
  dd { color: var(--erp-color-text-regular); overflow-wrap: anywhere; }
}

.wr-approval-table { width: 100%; }
.wr-approval-table th.el-table__cell .cell { font-weight: 400; }
.wr-approval-events { margin-bottom: 0; }

.wr-approval-actions {
  display: flex;
  justify-content: flex-end;
  gap: 20px;
  margin-top: auto;

  .el-button {
    min-width: 110px;
    height: 32px;
    margin-left: 0;
    border-radius: 5px;
    font-size: 13px;
    font-weight: 400;
  }

  .el-button--primary { min-width: 140px; }
}
</style>
