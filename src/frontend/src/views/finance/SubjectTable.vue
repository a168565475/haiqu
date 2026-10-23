<script setup lang="ts">
import { nextTick } from 'vue'
import type { DropdownInstance } from 'element-plus'
import type { FinanceSubject } from '@/types/financeSubjects'
defineProps<{ rows: FinanceSubject[]; busy: boolean; canChange: boolean; canDelete: boolean; tree?: boolean }>()
const emit = defineEmits<{ action: [action: string, row: FinanceSubject] }>()
let pending: { action: string; row: FinanceSubject } | undefined
const menus = new Map<string, DropdownInstance>()
function closeMenu(id: string) {
  menus.get(id)?.handleClose()
  document.querySelector<HTMLButtonElement>(`[data-subject-menu="${id}"]`)?.focus({preventScroll:true})
}
async function visibility(visible: boolean, row: FinanceSubject) {
  if (visible || pending?.row.id !== row.id) return
  const selected = pending; pending = undefined
  await nextTick()
  document.querySelector<HTMLButtonElement>(`[data-subject-menu="${row.id}"]`)?.focus({preventScroll:true})
  emit('action', selected.action, selected.row)
}
</script>
<template>
  <el-table :data="rows" height="100%" border row-key="id" highlight-current-row>
    <el-table-column label="费用类型" min-width="140"><template #default="{row}">{{row.path_names[0]}}</template></el-table-column>
    <el-table-column label="一级科目" min-width="140"><template #default="{row}">{{row.path_names[1] || '—'}}</template></el-table-column>
    <el-table-column label="二级科目" min-width="160"><template #default="{row}">{{row.path_names[2] || '—'}}</template></el-table-column>
    <el-table-column prop="full_path" label="完整路径" min-width="280" show-overflow-tooltip/>
    <el-table-column label="自身状态" width="100"><template #default="{row}"><el-tag :type="row.status==='ACTIVE'?'success':'info'">{{row.status==='ACTIVE'?'启用':'停用'}}</el-tag></template></el-table-column>
    <el-table-column label="有效状态" min-width="170"><template #default="{row}"><span :title="row.blocked_by_ancestor || ''">{{row.blocked_by_ancestor || (row.effective_status==='ACTIVE'?'启用':'自身停用')}}</span></template></el-table-column>
    <el-table-column v-if="tree" label="下级" width="100"><template #default="{row}"><el-button v-if="row.level<3" link @click="emit('action','expand',row)">{{row.child_count}} 项 · 展开</el-button><span v-else>末级</span></template></el-table-column>
    <el-table-column label="操作" width="100" fixed="right" align="center"><template #default="{row}">
      <el-dropdown :ref="(el: unknown)=>{if(el)menus.set(row.id,el as DropdownInstance);else menus.delete(row.id)}" trigger="click" placement="bottom-end" popper-class="finance-subject-popper" @command="(action: string)=>pending={action,row}" @visible-change="visibility($event,row)">
        <el-button link :disabled="busy" :data-subject-menu="row.id" @keydown.esc.stop.prevent="closeMenu(row.id)">更多<svg viewBox="0 0 12 12" aria-hidden="true" class="more-arrow"><path d="m3 4 3 3 3-3"/></svg></el-button>
        <template #dropdown><el-dropdown-menu @keydown.esc.stop.prevent="closeMenu(row.id)">
          <el-dropdown-item command="detail">详情</el-dropdown-item>
          <el-dropdown-item v-if="canChange" command="edit">编辑</el-dropdown-item>
          <el-dropdown-item v-if="canChange" command="toggle">{{row.status==='ACTIVE'?'停用':'启用'}}</el-dropdown-item>
          <el-dropdown-item v-if="canDelete" command="delete" divided :disabled="!row.can_delete" :title="row.delete_block_reason || ''"><span class="danger-action">{{row.can_delete?'删除':'含下级，不可删除'}}</span></el-dropdown-item>
        </el-dropdown-menu></template>
      </el-dropdown>
    </template></el-table-column>
    <template #empty><slot name="empty">暂无科目</slot></template>
  </el-table>
</template>

<style scoped lang="scss">
.more-arrow { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.5; margin-left: 4px; }
</style>
