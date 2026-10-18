<script setup lang="ts">
import { computed } from 'vue'
import { inquiryStepIndex, inquirySteps } from '@/views/inquiries/inquiryDetailState'
const props = defineProps<{ status: string; statusLabel: string; hasOwner: boolean }>()
const activeIndex = computed(() => inquiryStepIndex(props.status, props.hasOwner))
</script>

<template>
  <div v-if="activeIndex >= 0" class="status-progress" aria-label="询盘流转进度">
    <div v-for="(step, index) in inquirySteps" :key="step.code" class="progress-step"
      :class="{ done: index < activeIndex, current: index === activeIndex }"
      :aria-current="index === activeIndex ? 'step' : undefined">
      <span class="step-circle" aria-hidden="true">
        <svg v-if="index < activeIndex" class="step-check" viewBox="0 0 16 16" focusable="false">
          <path d="m3 8.5 3 3L13 4.5" />
        </svg>
        <template v-else>{{ index + 1 }}</template>
      </span>
      <span class="step-label">{{ step.label }}</span>
    </div>
  </div>
  <div v-else class="status-progress status-exception" role="status">
    <strong>{{ statusLabel }}</strong>
    <span>{{ status === 'DRAFT' ? '草稿提交后开始流转' : ['LOST', 'CLOSED', 'CANCELLED'].includes(status) ? '当前询盘流程已终止' : '当前状态暂未映射到流转步骤，请刷新后重试' }}</span>
  </div>
</template>

<style scoped lang="scss">
$flow-accent: var(--erp-color-brand);
.status-progress { display: flex; align-items: flex-start; min-height: 76px; padding: 8px 0; }
.progress-step { position: relative; display: flex; flex: 1 1 0; min-width: 0; align-items: center; flex-direction: column; gap: 8px; color: var(--erp-color-text-regular); font-size: 13px; line-height: 20px; text-align: center;
  &:not(:last-child)::after { content: ''; position: absolute; height: 2px; top: 13px; left: calc(50% + 14px); width: calc(100% - 28px); background: var(--erp-color-border); }
  &.done::after { background: $flow-accent; }
}
.step-circle { display: grid; place-items: center; flex-shrink: 0; width: 28px; height: 28px; border: 1px solid var(--erp-color-border); border-radius: 999px; background: var(--erp-color-surface); color: var(--erp-color-text-regular); font-size: 12px; line-height: 18px; font-weight: 500; }
.step-check { width: 16px; height: 16px; fill: none; stroke: var(--erp-color-text-inverse); stroke-linecap: round; stroke-linejoin: round; stroke-width: 2; }
.step-label { max-width: 100%; overflow-wrap: anywhere; }
.done .step-circle { background: $flow-accent; border-color: $flow-accent; color: var(--erp-color-text-inverse); }
.done .step-label { color: var(--erp-color-text-primary); font-weight: 500; }
.current { .step-circle { border-color: $flow-accent; color: $flow-accent; } .step-label { color: var(--erp-color-text-primary); font-weight: 600; } }
.error { .step-circle { border-color: var(--erp-color-danger-border); color: var(--erp-color-danger); } .step-label, .step-state { color: var(--erp-color-danger); font-weight: 600; } }
.step-state { color: var(--erp-color-text-regular); font-size: 11px; line-height: 16px; }
.status-exception { align-items: center; gap: 16px; padding-left: 0; color: var(--erp-color-text-regular); font-size: 13px; line-height: 20px; strong { color: var(--erp-color-danger); } }
</style>
