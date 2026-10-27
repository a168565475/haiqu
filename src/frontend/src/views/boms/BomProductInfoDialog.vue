<script setup lang="ts">
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { BomDetail } from '@/types/bom'

const props = defineProps<{
  bom: BomDetail
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <AppWindowDialog
    :model-value="props.modelValue"
    title="产品信息"
    width="640px"
    append-to-body
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="bom-product-info-dialog">
      <p class="bom-product-info-dialog__hint">以下为当前 BOM 保存的产品信息快照。图片不随 BOM 产品确认回写。</p>
      <dl>
        <div><dt>产品 ID</dt><dd>{{ props.bom.product_master_id || '尚未关联产品库' }}</dd></div>
        <div><dt>产品编号</dt><dd>{{ props.bom.product_number_snapshot || '—' }}</dd></div>
        <div><dt>产品编码</dt><dd>{{ props.bom.product_code_snapshot || '—' }}</dd></div>
        <div><dt>货号</dt><dd>{{ props.bom.item_number_snapshot || '—' }}</dd></div>
        <div><dt>类别</dt><dd>{{ props.bom.product_category_snapshot || '—' }}</dd></div>
        <div><dt>产品名称</dt><dd>{{ props.bom.product_name_snapshot || '—' }}</dd></div>
        <div><dt>规格</dt><dd>{{ props.bom.specification_snapshot || '—' }}</dd></div>
        <div><dt>单位</dt><dd>{{ props.bom.product_unit_name || '—' }}</dd></div>
        <div><dt>颜色</dt><dd>{{ props.bom.product_color_snapshot || '—' }}</dd></div>
        <div><dt>材质</dt><dd>{{ props.bom.material_snapshot || '—' }}</dd></div>
      </dl>
    </div>
    <template #footer><ElButton @click="emit('update:modelValue', false)">关闭</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.bom-product-info-dialog__hint { margin: 0 0 14px; color: var(--erp-color-text-secondary); font-size: 13px; }
.bom-product-info-dialog dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 16px; margin: 0; }
.bom-product-info-dialog dl > div { min-width: 0; padding: 10px 12px; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-subtle); }
.bom-product-info-dialog dt { margin-bottom: 4px; color: var(--erp-color-text-secondary); font-size: 12px; }
.bom-product-info-dialog dd { margin: 0; overflow-wrap: anywhere; color: var(--erp-color-text-primary); font-size: 13px; }
</style>
