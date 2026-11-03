<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { isAxiosError, isCancel } from 'axios'
import { useRoute } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import TubeOutsourcingPlanDetail from './TubeOutsourcingPlanDetail.vue'
import OutsourcingFlowActions from './OutsourcingFlowActions.vue'
import TubeOutsourcingDetailView from '@/views/outsourcing/TubeOutsourcingDetailView.vue'
import TubeCoatingReceiptView from '@/views/inventory/TubeCoatingReceiptView.vue'
import MetalProcessingP4View from '@/views/outsourcing/MetalProcessingP4View.vue'
import { fetchTubeOrder } from '@/api/tubeOutsourcing'
import { fetchOutsourcingOrder } from '@/api/outsourcing'
import { useIdentityOwnedStorage } from '@/composables/useIdentityOwnedStorage'
import type { UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'
import type { TubeOrderDetail } from '@/types/tubeOutsourcing'
import type { VersionedOutsourcingOrder } from '@/types/outsourcing'

const props = defineProps<{ record: UnifiedOutsourcingOrder; action: 'dispatch' | 'return' }>()
const emit = defineEmits<{ closed: []; updated: [] }>()
const route = useRoute()
const owned = useIdentityOwnedStorage({ storage: 'local', key: 'outsourcing-action-host' })
const identityBlocked = computed(() => !owned.isCurrent())
const allowed = computed(() => route.meta?.outsourcingWorkspace === 'warehouse' && props.record.warehouse_actions?.includes(props.action))
const tube = computed(() => props.record.record_type === 'TUBE')
const plan = computed(() => tube.value && props.record.is_plan)
const metal = computed(() => !tube.value && (props.record.record_type === 'REWORK' || props.record.detail_access === 'METAL' || props.record.direct_handoff))
const title = computed(() => props.action === 'dispatch' ? '材料发出' : '外发入库')
const order = ref<TubeOrderDetail | null>(null)
const regular = ref<VersionedOutsourcingOrder | null>(null)
const receiptView = ref<{ canClose: () => boolean } | null>(null)
const loading = ref(false)
const error = ref('')
let requestSequence = 0
let disposed = false
const needsLoad = computed(() => plan.value || (!tube.value && !metal.value))
const ready = computed(() => !needsLoad.value || Boolean(plan.value ? order.value : regular.value))

async function load() {
  if (!allowed.value || identityBlocked.value || !needsLoad.value) return
  const sequence = ++requestSequence
  loading.value = true; error.value = ''
  try {
    owned.assertCurrent()
    if (plan.value) {
      const result = await fetchTubeOrder(props.record.id, true)
      owned.assertCurrent()
      if (disposed || sequence !== requestSequence) return
      if (!result.is_plan) throw new Error('当前单据类型已变化，请刷新列表后重新办理。')
      order.value = result
    } else {
      const result = await fetchOutsourcingOrder(props.record.id, true)
      owned.assertCurrent()
      if (disposed || sequence !== requestSequence) return
      regular.value = result
    }
  } catch (cause) {
    if (!disposed && sequence === requestSequence && !isCancel(cause) && owned.isCurrent()) {
      error.value = isAxiosError(cause) ? cause.response?.data?.error?.message || cause.response?.data?.detail || '读取委外单失败，请重试。' : cause instanceof Error ? cause.message : '读取委外单失败，请重试。'
    }
  } finally { if (!disposed && sequence === requestSequence) loading.value = false }
}
function updatedPlan(value: TubeOrderDetail) { if (owned.isCurrent()) { order.value = value; emit('updated') } }
function updatedRegular(value: VersionedOutsourcingOrder) { if (owned.isCurrent()) { regular.value = value; emit('updated') } }
function updated() { if (owned.isCurrent()) emit('updated') }
function closeReceipt(done: () => void) { if (receiptView.value?.canClose() !== false) done() }
function close(value = false) { if (!value) emit('closed') }
onMounted(load)
onBeforeUnmount(() => { disposed = true; requestSequence += 1 })
</script>

<template>
  <AppWindowDialog v-if="identityBlocked || !allowed || !ready" :model-value="true" :title="title" :width="720" @update:model-value="close">
    <div v-loading="loading" class="action-loading">
      <ElAlert v-if="identityBlocked" title="身份尚未核验或已变化，请核验身份后重新打开。" type="warning" :closable="false" />
      <ElAlert v-else-if="!allowed" title="当前列表未开放此操作，请刷新后核对权限和单据状态。" type="warning" :closable="false" />
      <ElAlert v-else-if="error" :title="error" type="error" :closable="false" />
      <p v-else>正在读取最新委外单…</p>
    </div>
    <template #footer><ElButton @click="close()">关闭</ElButton><ElButton v-if="!identityBlocked && allowed && error" :loading="loading" @click="load">重新读取</ElButton></template>
  </AppWindowDialog>
  <template v-else>
    <TubeOutsourcingPlanDetail v-if="plan && order" :order="order" warehouse action-only :blocked="loading || Boolean(error)" :entry-action="action" @updated="updatedPlan" @refresh="load" @closed="close()" />
    <TubeOutsourcingDetailView v-else-if="tube && action === 'dispatch'" :order-id="record.id" :entry-action="action" action-only @updated="updated" @closed="close()" />
    <AppWindowDialog v-else-if="tube" :model-value="true" :title="title" :width="1800" :before-close="closeReceipt" class="warehouse-outsourcing-receipt-dialog" @update:model-value="close">
      <TubeCoatingReceiptView ref="receiptView" :order-id="record.id" embedded @updated="updated" @closed="close()" />
    </AppWindowDialog>
    <MetalProcessingP4View v-else-if="metal" :mode="record.record_type === 'REWORK' ? 'rework' : 'original'" :original-order-id="record.record_type === 'REWORK' ? undefined : record.id" :external-order-id="record.record_type === 'REWORK' ? record.id : undefined" :entry-action="action" action-only @updated="updated" @closed="close()" />
    <OutsourcingFlowActions v-else-if="regular" :detail="regular.data" :etag="regular.etag" :entry-action="action" hide-triggers @updated="updatedRegular" @closed="close()" />
    <AppWindowDialog v-if="error && ready" :model-value="true" title="委外单读取失败" :width="720" @update:model-value="close">
      <ElAlert :title="error" type="error" :closable="false" />
      <template #footer><ElButton @click="close()">关闭</ElButton><ElButton :loading="loading" @click="load">重新读取</ElButton></template>
    </AppWindowDialog>
  </template>
</template>

<style scoped>
.action-loading { min-height: 100px; }
</style>
