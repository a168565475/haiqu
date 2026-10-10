<script setup lang="ts">
import { reactive, watch } from 'vue'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'

interface ProductionTaskFilters {
  product_search: string
  delivery_dates: [string, string] | []
}

const props = defineProps<{
  modelValue: boolean
  filters: ProductionTaskFilters
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  apply: [filters: ProductionTaskFilters]
}>()

const form = reactive<ProductionTaskFilters>({
  product_search: '',
  delivery_dates: [],
})

function copyFilters() {
  form.product_search = props.filters.product_search
  form.delivery_dates = props.filters.delivery_dates.length ? [...props.filters.delivery_dates] : []
}

function reset() {
  form.product_search = ''
  form.delivery_dates = []
}

function apply() {
  emit('apply', {
    product_search: form.product_search.trim(),
    delivery_dates: form.delivery_dates.length ? [...form.delivery_dates] : [],
  })
  emit('update:modelValue', false)
}

watch(() => props.modelValue, visible => { if (visible) copyFilters() })
</script>

<template>
  <AppWindowDialog
    :model-value="modelValue"
    title="更多筛选"
    :width="596"
    :height="284"
    class="schedule-task-filter-dialog"
    destroy-on-close
    @update:model-value="value => emit('update:modelValue', value)"
    @close="emit('update:modelValue', false)"
  >
    <div class="task-filter-form">
      <label>
        <span>产品关键词</span>
        <ElInput v-model="form.product_search" clearable maxlength="200" placeholder="产品名称、货号或产品编号" />
      </label>
      <label>
        <span>交货日期</span>
        <ElDatePicker
          v-model="form.delivery_dates"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          popper-class="schedule-date-popper"
        />
      </label>
    </div>
    <template #footer>
      <ElButton @click="reset">重置</ElButton>
      <ElButton @click="emit('update:modelValue', false)">取消</ElButton>
      <ElButton type="primary" @click="apply">应用筛选</ElButton>
    </template>
  </AppWindowDialog>
</template>
