<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, ref, watch } from 'vue'

import type { ProductOption, UnitOption } from '@/types/productionTask'

const props = withDefaults(defineProps<{
  modelValue: boolean
  products: ProductOption[]
  units: UnitOption[]
  selectedId?: string
  canCreate?: boolean
  loading?: boolean
}>(), {
  selectedId: '',
  canCreate: false,
  loading: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  select: [product: ProductOption]
  create: []
}>()

const search = ref('')
const currentId = ref('')

const candidates = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return props.products
  return props.products.filter((item) => (
    [item.product_number, item.product_code, item.item_number, item.product_name, item.specification]
      .some((value) => String(value || '').toLowerCase().includes(keyword))
  ))
})

function unitLabel(unitId: string) {
  const unit = props.units.find((item) => item.id === unitId)
  return unit ? `${unit.unit_code} · ${unit.unit_name}` : '—'
}

function choose(product: ProductOption) {
  currentId.value = product.id
  emit('select', product)
}

watch(() => props.modelValue, (visible) => {
  if (!visible) return
  search.value = ''
  currentId.value = props.selectedId
})
</script>

<template>
  <ElDialog
    :model-value="modelValue"
    title="选择产品"
    width="980px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="product-picker-toolbar">
      <ElInput v-model="search" clearable placeholder="搜索产品编码、货号、品名或规格" />
      <ElButton v-if="canCreate" type="primary" @click="emit('create')">新增产品</ElButton>
    </div>
    <ElTable
      v-loading="loading"
      :data="candidates"
      height="460"
      highlight-current-row
      row-key="id"
      @row-click="choose"
    >
      <ElTableColumn label="选择" width="64" align="center">
        <template #default="{ row }">
          <ElRadio
            v-model="currentId"
            :value="row.id"
            :aria-label="`选择 ${row.product_name}`"
            @click.stop
            @change="choose(row)"
          />
        </template>
      </ElTableColumn>
      <ElTableColumn prop="product_code" label="产品编码" width="140" />
      <ElTableColumn prop="item_number" label="货号" width="140" />
      <ElTableColumn prop="product_name" label="品名" min-width="190" show-overflow-tooltip />
      <ElTableColumn prop="specification" label="规格" min-width="220" show-overflow-tooltip />
      <ElTableColumn label="单位" width="130">
        <template #default="{ row }">{{ unitLabel(row.default_unit_id) }}</template>
      </ElTableColumn>
      <template #empty><ElEmpty description="暂无可选产品" /></template>
    </ElTable>
  </ElDialog>
</template>

<style lang="scss" scoped>
.product-picker-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; margin-bottom: 14px; }
</style>
