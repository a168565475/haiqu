<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import type { ContactListItem } from '@/types/contact'

const props = withDefaults(defineProps<{
  rows: ContactListItem[]
  loading: boolean
  showCustomer: boolean
  visibleColumns: string[]
  canChange?: boolean
  canLeave?: boolean
  canDelete?: boolean
  compact?: boolean
  v2?: boolean
}>(), { canChange: false, canLeave: false, canDelete: false, compact: true, v2: false })

const emit = defineEmits<{
  selectionChange: [rows: ContactListItem[]]
  view: [row: ContactListItem]
  edit: [row: ContactListItem]
  history: [row: ContactListItem]
  leave: [row: ContactListItem]
  delete: [row: ContactListItem]
}>()

const compactViewport = ref(false)

function updateViewport(): void {
  compactViewport.value = window.innerWidth <= 1500
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (words.length >= 2) return `${words[0][0]}${words[1][0]}`.toUpperCase()
  return name.slice(0, 2).toUpperCase()
}

function interactionLabel(row: ContactListItem): string {
  if (!row.last_interaction) return row.status === 'LEFT' && row.left_effective_date
    ? `${row.left_effective_date.slice(0, 7)} · 离职`
    : '从未互动'
  const occurredAt = new Date(row.last_interaction.occurred_at)
  const hours = Math.max(0, Math.floor((Date.now() - occurredAt.getTime()) / 3_600_000))
  let relative = `${hours} 小时前`
  if (hours >= 24 && hours < 48) relative = '昨天'
  else if (hours >= 48 && hours < 24 * 30) relative = `${Math.floor(hours / 24)} 天前`
  else if (hours >= 24 * 30) relative = occurredAt.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  return `${relative} · ${row.last_interaction.communication_type || '沟通'}`
}

function sortedMethods(row: ContactListItem): ContactListItem['methods'] {
  const preferredOrder = ['EMAIL', 'MOBILE', 'PHONE']
  return [...row.methods]
    .sort((a, b) => {
      const aOrder = preferredOrder.indexOf(a.method_type)
      const bOrder = preferredOrder.indexOf(b.method_type)
      const normalizedAOrder = aOrder === -1 ? preferredOrder.length : aOrder
      const normalizedBOrder = bOrder === -1 ? preferredOrder.length : bOrder
      return normalizedAOrder - normalizedBOrder || a.method_type.localeCompare(b.method_type)
    })
}

function relationshipLabel(row: ContactListItem): string {
  if (row.marketing_opt_out) return '已退出营销'
  if (row.is_key_contact) return '关键联系人'
  if (row.is_primary_contact) return '主要联系人'
  return '—'
}

function roleLabels(row: ContactListItem): string {
  return row.active_roles.map((item) => item.role_type_display).join('、')
}

function handleMore(command: string, row: ContactListItem): void {
  if (command === 'view') emit('view', row)
  if (command === 'edit') emit('edit', row)
  if (command === 'history') emit('history', row)
  if (command === 'leave') emit('leave', row)
  if (command === 'delete') emit('delete', row)
}

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
})
onBeforeUnmount(() => window.removeEventListener('resize', updateViewport))
</script>

<template>
  <ElTable
    v-loading="loading"
    :data="rows"
    row-key="id"
    stripe
    :border="props.v2"
    class="contact-table"
    :class="{ 'is-compact': compact, 'contact-table--v2': props.v2 }"
    empty-text="暂无联系人"
    @selection-change="emit('selectionChange', $event)"
  >
    <ElTableColumn type="selection" width="48" reserve-selection />
    <ElTableColumn v-if="visibleColumns.includes('name')" label="姓名" :width="props.v2 ? 258 : 260">
      <template #default="{ row }">
        <div class="contact-name">
          <span class="contact-avatar">{{ initials(row.english_name || row.display_name) }}</span>
          <strong :title="row.display_name">{{ row.display_name }}</strong>
          <i v-if="row.is_primary_contact" title="主要联系人">{{ props.v2 ? '主要' : '主' }}</i>
        </div>
      </template>
    </ElTableColumn>
    <ElTableColumn v-if="showCustomer && visibleColumns.includes('customer')" label="客户" width="220">
      <template #default="{ row }">
        <div class="customer-cell" :title="row.customer.account_name">{{ row.customer.account_name }}</div>
        <small>{{ row.customer.account_code }}</small>
      </template>
    </ElTableColumn>
    <ElTableColumn v-if="visibleColumns.includes('position')" label="职位" :width="props.v2 ? 160 : 170">
      <template #default="{ row }"><span class="single-line">{{ row.position_title || '—' }}</span></template>
    </ElTableColumn>
    <ElTableColumn v-if="(props.v2 || !compactViewport) && visibleColumns.includes('department')" label="部门" width="120">
      <template #default="{ row }"><span class="single-line">{{ row.department_name || '—' }}</span></template>
    </ElTableColumn>
    <ElTableColumn v-if="visibleColumns.includes('roles')" label="决策角色" :width="props.v2 ? 130 : 150">
      <template #default="{ row }">
        <ElTooltip v-if="row.active_roles.length" :content="roleLabels(row)" placement="top">
          <ElTag effect="plain" class="role-tag" :class="{ 'is-decision-maker': row.active_roles[0].role_type === 'DECISION_MAKER' }">{{ row.active_roles[0].role_type_display }}</ElTag>
        </ElTooltip>
        <span v-else>—</span>
      </template>
    </ElTableColumn>
    <ElTableColumn v-if="visibleColumns.includes('methods')" label="联系方式" :width="props.v2 ? 330 : 210">
      <template #default="{ row }">
        <div v-if="sortedMethods(row).length" class="method-lines">
          <span v-for="method in sortedMethods(row).slice(0, props.v2 ? 2 : undefined)" :key="method.id" :title="method.display_value">{{ method.display_value }}</span>
        </div>
        <span v-else>—</span>
      </template>
    </ElTableColumn>
    <ElTableColumn v-if="visibleColumns.includes('interaction')" label="最近互动" :width="props.v2 ? 180 : 160">
      <template #default="{ row }"><span class="interaction-line">{{ interactionLabel(row) }}</span></template>
    </ElTableColumn>
    <ElTableColumn v-if="visibleColumns.includes('status')" label="任职状态" :width="props.v2 ? 100 : 110">
      <template #default="{ row }">
        <ElTag :type="row.status === 'ACTIVE' ? 'success' : row.status === 'LEFT' ? 'info' : 'warning'" class="status-tag">{{ row.status_display }}</ElTag>
      </template>
    </ElTableColumn>
    <ElTableColumn v-if="props.v2 && visibleColumns.includes('relationship')" label="关系与偏好" width="180">
      <template #default="{ row }"><span class="relationship-line">{{ relationshipLabel(row) }}</span></template>
    </ElTableColumn>
    <ElTableColumn label="操作" :width="props.v2 ? 128 : 96" fixed="right">
      <template #default="{ row }">
        <div v-if="props.v2" class="row-actions row-actions--v2">
          <button type="button" @click="emit('view', row)">查看</button>
          <button v-if="canChange && row.status !== 'LEFT'" type="button" @click="emit('edit', row)">编辑</button>
          <ElDropdown :persistent="false" trigger="click" @command="handleMore($event, row)">
            <button class="more-trigger" type="button" aria-label="更多联系人操作">···</button>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem command="history">任职历史</ElDropdownItem>
                <ElDropdownItem v-if="canLeave && row.status !== 'LEFT'" command="leave" divided>标记离职</ElDropdownItem>
                <ElDropdownItem v-if="canDelete" command="delete" divided>永久删除</ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </div>
        <div v-else class="row-actions">
          <ElDropdown :persistent="false" trigger="click" @command="handleMore($event, row)">
            <ElButton>更多</ElButton>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem command="view">查看</ElDropdownItem>
                <ElDropdownItem v-if="canChange && row.status !== 'LEFT'" command="edit">编辑</ElDropdownItem>
                <ElDropdownItem command="history">任职历史</ElDropdownItem>
                <ElDropdownItem v-if="canLeave && row.status !== 'LEFT'" command="leave" divided>标记离职</ElDropdownItem>
                <ElDropdownItem v-if="canDelete" command="delete" divided>永久删除</ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </div>
      </template>
    </ElTableColumn>
  </ElTable>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.contact-table { width: 100%; --el-table-header-bg-color: #f7f8fa; --el-table-row-hover-bg-color: #f4f4f5; --el-table-border-color: #edf0f4; }
.contact-table :deep(.el-table__header-wrapper th.el-table__cell) { height: 44px; padding: 0; color: #18181b; font-size: 12px; font-weight: 600; }
.contact-table :deep(.el-table__body-wrapper td.el-table__cell) { height: 48px; padding: 0; color: #30343b; font-size: 12px; }
.contact-table:not(.is-compact) :deep(.el-table__body-wrapper td.el-table__cell) { height: 56px; }
.contact-table :deep(.cell) { padding: 0 12px; line-height: 1.25; }
.contact-table :deep(.el-table-column--selection .cell) { padding: 0 14px; }
.contact-name { min-width: 0; display: flex; align-items: center; gap: 8px; }
.contact-name strong, .customer-cell, .single-line, .interaction-line { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.contact-name strong { color: #18181b; font-size: 12px; font-weight: 500; }
.contact-name i { flex: none; width: 20px; height: 20px; display: inline-grid; place-items: center; border-radius: 5px; color: #18181b; background: #f4f4f5; font-size: 10px; font-style: normal; }
.contact-avatar { flex: none; width: 28px; height: 28px; display: inline-grid; place-items: center; border-radius: 50%; color: #5f6673; background: #f1f3f6; font-size: 10px; font-weight: 500; }
.customer-cell { color: #18181b; }
small { display: block; margin-top: 2px; color: #8b929e; font-size: 10px; }
.role-tag, .status-tag { min-width: 64px; height: 24px; justify-content: center; border: 0; border-radius: 6px; font-size: 11px; }
.role-tag { color: #18181b; background: #f4f4f5; }
.method-lines { display: flex; flex-direction: column; gap: 2px; }
.method-lines span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.method-lines span:first-child { color: #30343b; font-size: 11px; }
.method-lines span:last-child { color: #8b929e; font-size: 10px; }
.interaction-line { display: block; color: #5f6673; font-size: 11px; }
.row-actions { display: flex; align-items: center; }
.row-actions :deep(.el-button) { width: 64px; height: 28px; margin: 0; padding: 0; border-color: #d4d4d8; border-radius: 8px; color: #3f3f46; background: #fff; font-size: 12px; }
.row-actions :deep(.el-button:hover) { border-color: #a1a1aa; color: #18181b; background: #f4f4f5; }

.contact-table--v2 {
  min-width: 1634px;
  font-family: token.$crm-font-body;
  --el-table-header-bg-color: #{token.$crm-color-subtle};
  --el-table-row-hover-bg-color: #{token.$crm-color-row-hover};
  --el-table-border-color: #{token.$crm-border-subtle};
}

.contact-table--v2 :deep(.el-table__header-wrapper th.el-table__cell) {
  height: 44px;
  color: token.$crm-text-primary;
  background: token.$crm-color-subtle;
  font-size: 12px;
  font-weight: 600;
}

.contact-table--v2 :deep(.el-table__body-wrapper td.el-table__cell),
.contact-table--v2:not(.is-compact) :deep(.el-table__body-wrapper td.el-table__cell) {
  height: 62px;
  color: token.$crm-text-regular;
  background: token.$crm-color-surface;
  font-size: 12px;
}

.contact-table--v2 :deep(.el-table__row--striped td.el-table__cell) {
  background: #faf7f0;
}

.contact-table--v2 :deep(.cell) {
  padding: 0 14px;
}

.contact-table--v2 .contact-avatar {
  width: 32px;
  height: 32px;
  color: token.$crm-warning;
  background: token.$crm-warning-soft;
  font-size: 11px;
}

.contact-table--v2 .contact-name {
  gap: 12px;
}

.contact-table--v2 .contact-name strong {
  min-width: 0;
  color: token.$crm-text-primary;
  font-size: 13px;
  font-weight: 600;
}

.contact-table--v2 .contact-name i {
  width: auto;
  height: 24px;
  padding: 0 9px;
  border-radius: token.$crm-radius-2;
  color: token.$crm-warning;
  background: token.$crm-warning-soft;
  font-size: 11px;
  font-weight: 500;
}

.contact-table--v2 .role-tag,
.contact-table--v2 .status-tag {
  min-width: 64px;
  height: 24px;
  border-radius: token.$crm-radius-2;
}

.contact-table--v2 .role-tag {
  color: token.$crm-text-secondary;
  background: token.$crm-color-subtle;
}

.contact-table--v2 .role-tag.is-decision-maker {
  color: token.$crm-warning;
  background: token.$crm-warning-soft;
}

.contact-table--v2 .status-tag.el-tag--success {
  color: token.$crm-success;
  background: token.$crm-success-soft;
}

.contact-table--v2 .status-tag.el-tag--info {
  color: token.$crm-text-secondary;
  background: token.$crm-color-subtle;
}

.contact-table--v2 .method-lines {
  gap: 4px;
}

.contact-table--v2 .method-lines span:first-child {
  color: token.$crm-text-regular;
  font-size: 12px;
}

.contact-table--v2 .method-lines span:last-child,
.contact-table--v2 .interaction-line,
.contact-table--v2 .relationship-line {
  color: token.$crm-text-secondary;
  font-size: 11px;
}

.row-actions--v2 {
  justify-content: center;
  gap: 9px;
  white-space: nowrap;
}

.row-actions--v2 > button,
.row-actions--v2 .more-trigger {
  height: 28px;
  padding: 0;
  border: 0;
  color: token.$crm-primary;
  background: transparent;
  font-family: token.$crm-font-body;
  font-size: 11px;
  cursor: pointer;
}

.row-actions--v2 .more-trigger {
  width: 22px;
  color: token.$crm-text-secondary;
  font-size: 14px;
  letter-spacing: -2px;
}

.row-actions--v2 > button:hover,
.row-actions--v2 .more-trigger:hover {
  color: token.$crm-primary-hover;
}
</style>
