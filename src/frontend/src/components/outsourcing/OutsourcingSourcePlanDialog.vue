<script setup lang="ts">
import { computed, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

import { fetchOutsourcingSourcePlans } from '@/api/outsourcing'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type {
  OutsourcingCraftOption,
  OutsourcingSourcePlan,
  OutsourcingSourceProduct,
} from '@/types/outsourcing'

const props = defineProps<{
  modelValue: boolean
  craft: OutsourcingCraftOption
  selectedPlan: OutsourcingSourcePlan | null
  selectedProductIds: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [plan: OutsourcingSourcePlan, productIds: string[]]
}>()

const loading = ref(false)
const rows = ref<OutsourcingSourcePlan[]>([])
const search = ref('')
const total = ref(0)
const page = ref(1)
const pendingPlanId = ref('')
const pendingPlanSnapshot = ref<OutsourcingSourcePlan | null>(null)
const pendingProductIds = ref<string[]>([])

const pendingPlan = computed(() => pendingPlanSnapshot.value)
const selectedCount = computed(() => pendingProductIds.value.length)
const craftTone = computed(() => ({
  SEWING: 'sewing',
  CUTTING: 'cutting',
  POWDER_COATING: 'spray',
  SCREEN_PRINTING: 'printing',
} as Record<string, string>)[props.craft.outsourcing_code || ''] || 'neutral')

function errorText(error: unknown): string {
  if (!(error instanceof AxiosError)) return '排产计划加载失败，请稍后重试。'
  const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return data?.error?.message || data?.detail || '排产计划加载失败，请稍后重试。'
}

function formatQuantity(product: OutsourcingSourceProduct): string {
  return `${Number(product.planned_quantity || 0).toLocaleString('zh-CN')} ${product.unit_name}`
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const result = await fetchOutsourcingSourcePlans({
      craft_id: props.craft.id,
      search: search.value.trim() || undefined,
      page: page.value,
      page_size: 50,
    })
    rows.value = result.data
    total.value = result.meta.total
    const refreshedPlan = rows.value.find(item => item.id === pendingPlanId.value)
    if (refreshedPlan) {
      pendingPlanSnapshot.value = refreshedPlan
      const allowedIds = new Set(refreshedPlan.products.map(product => product.id))
      pendingProductIds.value = pendingProductIds.value.filter(id => allowedIds.has(id))
    }
  } catch (error) {
    rows.value = []
    total.value = 0
    ElMessage.error(errorText(error))
  } finally {
    loading.value = false
  }
}

function open(): void {
  search.value = ''
  page.value = 1
  pendingPlanId.value = props.selectedPlan?.id || ''
  pendingPlanSnapshot.value = props.selectedPlan
  pendingProductIds.value = [...props.selectedProductIds]
  void load()
}

function selectPlan(plan: OutsourcingSourcePlan): void {
  if (pendingPlanId.value === plan.id) return
  pendingPlanId.value = plan.id
  pendingPlanSnapshot.value = plan
  pendingProductIds.value = plan.products.map(product => product.id)
}

function toggleProduct(productId: string, checked: boolean): void {
  if (!pendingPlan.value) return
  const allowed = new Set(pendingPlan.value.products.map(product => product.id))
  if (checked) pendingProductIds.value = [...new Set([...pendingProductIds.value, productId])].filter(id => allowed.has(id))
  else pendingProductIds.value = pendingProductIds.value.filter(id => id !== productId)
}

function confirm(): void {
  if (!pendingPlan.value) {
    ElMessage.warning('请选择一张排产计划。')
    return
  }
  if (!pendingProductIds.value.length) {
    ElMessage.warning('请至少选择一个符合工艺的产品。')
    return
  }
  emit('confirm', pendingPlan.value, [...pendingProductIds.value])
  emit('update:modelValue', false)
}
</script>

<template>
  <AppWindowDialog
    :model-value="modelValue"
    :width="1260"
    :height="730"
    class="outsourcing-source-dialog"
    title="选择排产计划"
    destroy-on-close
    @open="open"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="source-dialog-layout">
      <aside class="source-dialog-aside">
        <h3>来源信息</h3>
        <dl>
          <div><dt>外协工艺</dt><dd><span class="source-craft-tag" :class="`craft-${craftTone}`">{{ craft.name }}</span></dd></div>
          <div><dt>选择说明</dt><dd>仅显示已生成排产计划，且产品明确包含“{{ craft.name }}”工艺的数据。</dd></div>
          <div><dt>选择限制</dt><dd>只能选择 1 张排产计划，可勾选其中多个符合工艺的产品。</dd></div>
        </dl>
      </aside>

      <section class="source-dialog-main">
        <div class="source-dialog-toolbar">
          <ElInput
            v-model="search"
            :prefix-icon="Search"
            clearable
            maxlength="200"
            placeholder="搜索排产计划号、生产任务单号、产品"
            @keyup.enter="page = 1; load()"
            @clear="page = 1; load()"
          />
          <ElButton :icon="Refresh" :loading="loading" @click="load">刷新</ElButton>
        </div>

        <div v-loading="loading" class="source-plan-list">
          <div class="source-plan-header source-plan-grid">
            <span>选择</span><span>排产计划号</span><span>生产任务单基本信息</span><span>符合工艺产品</span><span>排产日期</span>
          </div>
          <template v-if="rows.length">
            <div v-for="plan in rows" :key="plan.id" class="source-plan-group" :class="{ 'is-selected': pendingPlanId === plan.id }">
              <div class="source-plan-row source-plan-grid" @click="selectPlan(plan)">
                <span class="radio-cell"><ElRadio :model-value="pendingPlanId" :value="plan.id" aria-label="选择排产计划" @click.stop="selectPlan(plan)" /></span>
                <strong>{{ plan.schedule_number }}</strong>
                <div class="task-basic-cell">
                  <strong>{{ plan.production_task_number }}</strong>
                </div>
                <span>{{ plan.matching_product_count }} 个产品</span>
                <span>{{ plan.schedule_date }}</span>
              </div>

              <div v-if="pendingPlanId === plan.id" class="source-product-table">
                <div class="source-product-header source-product-grid"><span>选择</span><span>产品信息</span><span>数量</span><span>产品厂外工艺</span></div>
                <div v-for="product in plan.products" :key="product.id" class="source-product-row source-product-grid" @click="toggleProduct(product.id, !pendingProductIds.includes(product.id))">
                  <span><ElCheckbox :model-value="pendingProductIds.includes(product.id)" aria-label="选择产品" @click.stop @change="toggleProduct(product.id, Boolean($event))" /></span>
                  <div class="source-product-info">
                    <span class="mini-line-art" aria-hidden="true"><i /><b /></span>
                    <div><strong>{{ product.product_number || product.item_number || '—' }} {{ product.product_name }}</strong><small>{{ product.specification || '未填写规格' }} · {{ product.color_name || '未填写颜色' }}</small></div>
                  </div>
                  <span>{{ formatQuantity(product) }}</span>
                  <span><span class="source-craft-tag" :class="`craft-${craftTone}`">厂外{{ product.craft_name }}</span></span>
                </div>
              </div>
            </div>
          </template>
          <div v-else-if="!loading" class="source-plan-empty">暂无符合“{{ craft.name }}”工艺的可外发排产计划</div>
        </div>
        <ElPagination
          v-if="total > 50"
          v-model:current-page="page"
          :page-size="50"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="load"
        />
      </section>
    </div>

    <template #footer>
      <div class="source-dialog-footer">
        <span>已选 {{ pendingPlan ? 1 : 0 }} 张计划、{{ selectedCount }} 个产品</span>
        <div><ElButton @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" :disabled="!pendingPlan || !selectedCount" @click="confirm">确认选择</ElButton></div>
      </div>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
$surface: var(--erp-color-surface);
$surface-muted: var(--erp-color-subtle);
$border: var(--erp-color-border);
$divider: var(--erp-color-border-subtle);
$text: var(--erp-color-text-primary);
$regular: var(--erp-color-text-regular);
$secondary: var(--erp-color-text-secondary);
$weak: var(--erp-color-text-muted);
$brand: var(--erp-color-brand);

.outsourcing-source-dialog {
  --el-color-primary: #{$brand};
  color: $regular;
  background: $surface;

  :deep(> .app-window-dialog__body) { padding: 20px 22px 14px; overflow: hidden; }
  :deep(> .app-window-dialog__footer) { padding: 12px 22px 16px; }
}

.source-dialog-layout { display: grid; height: 100%; min-height: 0; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; }
.source-dialog-aside { overflow: hidden; border: 1px solid $border; border-radius: 5px; background: $surface; }
.source-dialog-aside h3 { height: 46px; margin: 0; padding: 13px 18px; border-bottom: 1px solid $border; color: $text; background: $surface-muted; font-size: 16px; }
.source-dialog-aside dl { display: grid; gap: 28px; margin: 0; padding: 28px 18px; }
.source-dialog-aside dl > div { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 10px; }
.source-dialog-aside dt { color: $secondary; }
.source-dialog-aside dd { margin: 0; color: $regular; font-size: 13px; line-height: 21px; }
.source-craft-tag { display: inline-flex; height: 24px; min-width: 56px; align-items: center; justify-content: center; padding: 0 12px; border-radius: 999px; color: var(--erp-color-text-inverse); font-size: 12px; white-space: nowrap; }
.craft-sewing { background: var(--erp-tag-brand-background); }
.craft-cutting { background: var(--erp-tag-info-background); }
.craft-spray { background: var(--erp-tag-success-background); }
.craft-printing { background: var(--erp-tag-warning-background); }
.craft-neutral { background: var(--erp-tag-neutral-background); }

.source-dialog-main { display: flex; min-width: 0; min-height: 0; flex-direction: column; }
.source-dialog-toolbar { display: flex; height: 32px; flex: none; justify-content: space-between; margin: 20px 0 26px 10px; }
.source-dialog-toolbar .el-input { width: 480px; }
.source-dialog-toolbar .el-button { min-width: 112px; }
.source-plan-list { min-height: 0; flex: 1; overflow: auto; border: 1px solid $border; border-radius: 5px; background: $surface; }
.source-plan-grid { display: grid; grid-template-columns: 64px 170px minmax(280px, 1fr) 150px 140px; align-items: center; }
.source-plan-header { position: sticky; z-index: 1; top: 0; height: 44px; color: $text; background: $surface-muted; font-size: 13px; font-weight: 500; }
.source-plan-header span, .source-plan-row > * { padding: 0 16px; }
.source-plan-group { border-top: 1px solid $divider; &:first-of-type { border-top: 0; } }
.source-plan-group.is-selected { margin-bottom: 16px; }
.source-plan-row { min-height: 50px; cursor: pointer; &:hover { background: var(--erp-color-hover); } }
.source-plan-row > strong { color: $regular; font-size: 13px; }
.radio-cell { display: flex; align-items: center; justify-content: center; }
.task-basic-cell { display: grid; }
.task-basic-cell strong { color: $regular; font-size: 13px; font-weight: 500; }

.source-product-table { margin: 0 16px 16px 32px; overflow: hidden; border: 1px solid $border; border-radius: 5px; }
.source-product-grid { display: grid; grid-template-columns: 64px minmax(330px, 1fr) 160px 190px; align-items: center; }
.source-product-header { height: 42px; color: $text; background: $surface-muted; font-size: 13px; font-weight: 500; }
.source-product-header span, .source-product-row > * { padding: 0 16px; }
.source-product-row { min-height: 64px; border-top: 1px solid $divider; cursor: pointer; &:hover { background: var(--erp-color-hover); } }
.source-product-info { display: flex; min-width: 0; align-items: center; gap: 12px; }
.source-product-info > div { display: grid; min-width: 0; gap: 3px; }
.source-product-info strong { overflow: hidden; color: $regular; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.source-product-info small { color: $weak; font-size: 12px; }
.mini-line-art { position: relative; width: 40px; height: 40px; flex: none; border: 1px solid $border; border-radius: 4px; background: var(--erp-color-subtle); }
.mini-line-art::before { position: absolute; top: 8px; left: 11px; width: 17px; height: 15px; border: 1.5px solid var(--erp-color-text-muted); border-radius: 2px 2px 4px 4px; content: ''; transform: skew(-5deg); }
.mini-line-art i, .mini-line-art b { position: absolute; top: 22px; width: 1px; height: 11px; background: var(--erp-color-text-muted); }
.mini-line-art i { left: 13px; transform: rotate(12deg); }
.mini-line-art b { right: 12px; transform: rotate(-12deg); }
.source-plan-empty { display: grid; min-height: 280px; place-items: center; color: $weak; }
.source-dialog-main .el-pagination { justify-content: flex-end; margin-top: 10px; }
.source-dialog-footer { display: flex; width: 100%; align-items: center; justify-content: space-between; color: $regular; }
.source-dialog-footer > div { display: flex; gap: 12px; }
.source-dialog-footer .el-button { min-width: 112px; }
.source-dialog-footer :deep(.el-button--primary:not(.is-disabled)),
.source-dialog-footer :deep(.el-button--primary:not(.is-disabled):hover),
.source-dialog-footer :deep(.el-button--primary:not(.is-disabled):focus),
.source-dialog-footer :deep(.el-button--primary:not(.is-disabled):active) {
  border-color: var(--erp-button-primary-border);
  color: var(--erp-color-text-inverse);
  background: var(--erp-button-primary-surface);
  transition: none;
}

@media (max-width: 1000px) {
  .source-dialog-layout { grid-template-columns: 200px minmax(760px, 1fr); }
  .source-dialog-main { overflow-x: auto; }
}
</style>
