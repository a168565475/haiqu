<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import * as api from '@/api/access'
import type { DeletionItem, DeletionKind, DeletionPreview } from '@/types/access'

const props = defineProps<{ kind: DeletionKind; items: DeletionItem[] }>()
const emit = defineEmits<{ close: []; deleted: [selfDeleted: boolean] }>()
const preview = ref<DeletionPreview>(), error = ref(''), busy = ref(false), saving = ref(false)
let sequence = 0
onBeforeUnmount(() => { sequence++ })
watch(() => props.items, async items => {
  const current = ++sequence
  preview.value = undefined; error.value = ''
  if (!items.length) return
  busy.value = true
  try { const result = await api.previewDeletion(props.kind, items); if (current === sequence) preview.value = result }
  catch (cause) { if (current === sequence) error.value = api.accessError(cause) }
  finally { if (current === sequence) busy.value = false }
}, { immediate: true })
async function submit() {
  if (!preview.value || saving.value || busy.value) return
  saving.value = true; error.value = ''
  try {
    const result = await api.deleteSelected(props.kind, props.items, preview.value)
    emit('deleted', result.self_deleted); emit('close'); ElMessage.success(`已删除 ${result.rows.length} 条记录`)
  } catch (cause) { preview.value = undefined; error.value = api.accessError(cause) }
  finally { saving.value = false }
}
</script>

<template>
  <AppWindowDialog :model-value="items.length > 0" title="确认删除" :width="760" :before-close="done => { if (!saving) done() }" @update:model-value="value => { if (!value && !saving) emit('close') }">
    <div class="access-dialog">
      <p v-if="busy" role="status">正在核对删除影响…</p>
      <p v-if="error" class="access-warning" role="alert">{{ error }}</p>
      <template v-if="preview">
        <p>将删除 {{ preview.rows.length }} 条记录。<template v-if="kind === 'employees'">员工删除后，其账号不能继续登录；删除当前登录员工后将退出登录。</template></p>
        <div class="delete-preview"><table><thead><tr><th>名称</th><th>账号</th><th>处理方式</th></tr></thead><tbody><tr v-for="row in preview.rows" :key="row.id"><td>{{ row.name }}</td><td>{{ row.account || '—' }}</td><td>{{ row.reason }}</td></tr></tbody></table></div>
      </template>
    </div>
    <template #footer><div class="access-actions access-dialog-footer"><button :disabled="saving" @click="emit('close')">取消</button><button class="primary" :disabled="busy || saving || !preview" @click="submit">{{ saving ? '删除中…' : '确认删除' }}</button></div></template>
  </AppWindowDialog>
</template>

<style scoped>
.delete-preview { max-height: 50vh; overflow: auto; }
.delete-preview td { padding: 8px; }
</style>
