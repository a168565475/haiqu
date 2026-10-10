<script setup lang="ts">
import SampleProductImage from '@/components/samples/SampleProductImage.vue'
import { computed, ref } from 'vue'
import SampleReadonlyField from './SampleReadonlyField.vue'
import SampleApplicationSummary from './SampleApplicationSummary.vue'
import type { SampleDetail } from '@/types/sample'
import { sampleProductFieldLabel, sampleProductsLabel, sampleQuantityLabel } from '@/utils/samplePresentation'
const props = defineProps<{ sample: SampleDetail }>()
const expanded = ref(false)
const fields = computed(() => [
  { label: '客户', value: props.sample.customer_name },
  { label: '产品名称', value: sampleProductsLabel(props.sample) },
  { label: '产品规格', value: sampleProductFieldLabel(props.sample, 'specification') },
  { label: '打样数量', value: sampleQuantityLabel(props.sample) },
  { label: '期望完成', value: props.sample.sample_due_date || props.sample.requested_due_at?.slice(0, 10) },
])
</script>

<template>
  <section class="material-application-info" :class="{ expanded }">
    <header><h2>申请与样品信息</h2><ElButton link :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? '收起' : '展开查看' }}</ElButton></header>
    <div class="material-application-summary"><SampleProductImage class="product-image" :src="sample.reference_image ? `/api/v1/sample-requests/${sample.id}/business-files/${sample.reference_image}/` : ''" /><div class="summary-content"><div class="summary-fields"><SampleReadonlyField v-for="field in fields" :key="field.label" :label="field.label" :value="field.value" /></div><p :title="sample.purpose || '—'">特殊要求：{{ sample.purpose || '—' }}</p></div></div>
    <SampleApplicationSummary v-if="expanded" :sample="sample" class="expanded-summary" />
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/crm/mixins' as mixin;
.material-application-info { height: 200px; flex: none; padding: 24px; border-radius: 4px; background: token.$crm-color-surface; box-shadow: inset 0 0 0 1px token.$crm-border-subtle; }
header { display: flex; height: 30px; justify-content: space-between; margin-bottom: 12px; }
h2 { margin: 0; font-family: token.$crm-font-display; font-size: 22px; line-height: 30px; }
.material-application-info header :deep(.el-button.is-link) { color: token.$crm-text-secondary; font-size: 14px; }
.material-application-summary { display: flex; height: 110px; gap: 24px; }
.product-image { display: grid; width: 132px; height: 110px; flex: none; place-items: center; border: 1px solid token.$crm-border-subtle; border-radius: 4px; color: token.$crm-text-muted; font-size: 12px; }
.summary-content { flex: 1; min-width: 0; }
.summary-fields { display: grid; grid-template-columns: minmax(0, 280fr) minmax(0, 230fr) minmax(0, 360fr) minmax(0, 200fr) minmax(0, 280fr); gap: 20px; }
.summary-fields :deep(.field-value) { padding-left: 5px; border-radius: 0; box-shadow: none; }
.summary-content p { @include mixin.text-ellipsis; height: 36px; margin: 14px 0 0; padding: 7px 8px; background: token.$crm-color-page; font-size: 13px; line-height: 22px; }
.expanded { height: auto; }
.expanded-summary { margin-top: 24px; }
</style>
