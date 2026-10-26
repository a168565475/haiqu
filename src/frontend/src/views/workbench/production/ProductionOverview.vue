<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Calendar, OfficeBuilding, Van, Box, Tickets, FullScreen, Close } from '@element-plus/icons-vue'
import type { ProductionDashboardPayload, ProductionDashboardSection, ProductionDashboardTask } from '@/types/productionDashboard'
import ProductionProgress from './ProductionProgress.vue'
import ProductionOverviewTodo from './ProductionOverviewTodo.vue'
import { useModuleFocus, type OverviewModuleKey } from './useModuleFocus'

const props = defineProps<{ data: ProductionDashboardPayload }>()
const emit = defineEmits<{ openDay: [date: string] }>()
const root = ref<HTMLElement>()
const { activeModule, transitionTo, onKeydown, isAnimating } = useModuleFocus(root)
const modules = [
  { key: 'delivery', title: '交付节奏', icon: Calendar },
  { key: 'production', title: '厂内进度', icon: OfficeBuilding },
  { key: 'outsourcing', title: '外发回货', icon: Van },
  { key: 'output', title: '今日入库', icon: Box },
  { key: 'todo', title: '待处理事项', icon: Tickets },
] as const
function readable<T>(section: ProductionDashboardSection<T>): T | null {
  return section.state === 'READY' || section.state === 'EMPTY' ? section.data : null
}
const tasks = computed(() => readable(props.data.sections.tasks))
const outsourcing = computed(() => readable(props.data.sections.outsourcing))
const receipts = computed(() => readable(props.data.sections.receipts))
const leadTask = computed(() => tasks.value?.items[0])
const chartMax = computed(() => Math.max(1, ...(tasks.value?.due_series.map(day => day.count) ?? [])))
const businessToday = computed(() => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(props.data.generated_at)))
const activeTitle = computed(() => modules.find(module => module.key === activeModule.value)?.title)
const otherModules = computed(() => modules.filter(module => module.key !== activeModule.value))
const positions: Record<OverviewModuleKey, string> = {
  delivery: 'delivery', production: 'production', outsourcing: 'outsourcing', output: 'output', todo: 'todo',
}
function modulePosition(key: OverviewModuleKey) {
  if (!activeModule.value) return { '--po-area': positions[key] }
  if (key === activeModule.value) return { '--po-area': '1 / 1 / 2 / 5' }
  const index = otherModules.value.findIndex(item => item.key === key)
  return { '--po-area': `2 / ${index + 1}`, '--po-compact-area': `${2 + Math.floor(index / 2)} / ${1 + index % 2 * 2} / span 1 / span 2` }
}
function viewFor(key: OverviewModuleKey) { return !activeModule.value ? 'overview' : activeModule.value === key ? 'detail' : 'mini' }
function message(section: ProductionDashboardSection<unknown>, empty: string) {
  if (section.state === 'FORBIDDEN') return section.reason || '暂无此模块查看权限'
  if (section.state === 'UNKNOWN') return section.reason || '数据暂不可用，请稍后刷新'
  return empty
}
function quantity(value: string | number | null | undefined) {
  if (value == null || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(number) : '—'
}
function date(value: string | null | undefined) { return value ? value.slice(5, 10).replace('-', '/') : '未设日期' }
function taskName(task: ProductionDashboardTask) { return task.products.map(product => product.name).join('、') || task.task_number }
function dueText(task: ProductionDashboardTask) {
  if (task.days_to_due === null) return '未设交期'
  if (['COMPLETED', 'CANCELLED'].includes(task.status)) return task.status_display
  return task.days_to_due < 0 ? `已逾期 ${Math.abs(task.days_to_due)} 天` : task.days_to_due === 0 ? '今天到期' : `剩余 ${task.days_to_due} 天`
}
function overdue(task: ProductionDashboardTask) { return task.days_to_due !== null && task.days_to_due < 0 && !['COMPLETED', 'CANCELLED'].includes(task.status) }
function safeHref(href: string) {
  return /^\/(?:production-tasks|workshop\/(?:scheduling|plans|outsourcing|work-reports)|inventory\/finished-goods)(?:[/?#]|$)/.test(href) && !/[\\\s]/.test(href) && !href.includes('..') ? href : undefined
}
function outsourceLate(value: string | null) { return value !== null && value < businessToday.value }
function scheduleText(task: ProductionDashboardTask) {
  if (task.schedule_id) return '已有排产'
  if (Object.values(task.stages).some(stage => stage.label === '尚未排产')) return '尚未排产'
  return '排产情况待核实'
}
function miniValue(key: OverviewModuleKey) {
  if (key === 'delivery') return tasks.value ? `${tasks.value.counts.overdue} 单逾期` : '暂不可用'
  if (key === 'production') return tasks.value ? `${tasks.value.total} 单范围内任务` : '暂不可用'
  if (key === 'outsourcing') return outsourcing.value ? `${outsourcing.value.pending_count} 单待回` : '暂不可用'
  return receipts.value ? `${receipts.value.today_count} 笔入库` : '暂不可用'
}
const stages = [ ['metal', '金工汇总'], ['sewing', '裁缝汇总'], ['assembly', '成品入库'] ] as const
</script>

<template>
  <section ref="root" class="production-overview" data-testid="production-overview" :data-active-module="activeModule || 'overview'" :data-animating="isAnimating" @keydown="onKeydown">
    <div class="po-context"><span>{{ activeTitle ? `生产总览 / ${activeTitle}` : '5 个概览模块 · 点击展开详情' }}</span><span>未来 {{ data.filters.days }} 天及历史逾期 · 按可查看范围</span></div>
    <div class="po-stage" :class="{ 'is-focused': activeModule }">
      <div v-if="activeModule" class="po-dock" aria-hidden="true" />
      <article v-for="module in modules" :key="module.key" class="po-module" :class="[`po-module--${module.key}`, `is-${viewFor(module.key)}`]" :data-module="module.key" :style="modulePosition(module.key)" :aria-label="module.title">
        <button v-if="activeModule !== module.key" type="button" class="po-open" data-module-open :aria-label="`${activeModule ? '切换到' : '展开'}${module.title}`" :aria-expanded="false" @click="transitionTo(module.key)" />
        <header class="po-module-head"><h2><component :is="module.icon" aria-hidden="true" />{{ module.title }}</h2><button v-if="activeModule === module.key" class="po-close" data-module-close type="button" :aria-label="`收起${module.title}`" @click="transitionTo(null)"><Close aria-hidden="true" />收起</button><FullScreen v-else class="po-expand" aria-hidden="true" /></header>

        <ProductionOverviewTodo v-if="module.key === 'todo'" :view="viewFor('todo')" :refresh-key="data.generated_at" />
        <div v-else-if="viewFor(module.key) === 'mini'" class="po-mini"><span>{{ miniValue(module.key) }}</span></div>
        <template v-else-if="module.key === 'delivery'">
          <div v-if="tasks" class="po-content">
            <div class="po-summary"><strong class="po-number po-danger">{{ tasks.counts.overdue }}<small>单逾期</small></strong><span class="po-muted">未来 3 天到期 {{ tasks.counts.due_soon }} 单</span></div>
            <div class="po-chart" :aria-label="`未来 ${data.filters.days} 天交期任务分布`"><div v-for="day in tasks.due_series" :key="day.date" class="po-column"><span>{{ day.count }}</span><button v-if="activeModule === 'delivery'" class="po-bar pd-chart__bar" type="button" :style="{ height: `${day.count / chartMax * 76}px` }" :aria-label="`${day.date}，${day.count} 单到期任务`" @click="emit('openDay', day.date)" /><span v-else class="po-bar" :style="{ height: `${day.count / chartMax * 76}px` }" /><time :datetime="day.date" :title="day.date">{{ day.date.slice(5, 7) }}/<wbr />{{ day.date.slice(8, 10) }}</time></div></div>
            <template v-if="activeModule === 'delivery'">
              <div class="po-state-counts"><span v-for="item in tasks.status_distribution" :key="item.status">{{ item.label }} <b>{{ item.count }}</b></span></div>
              <div v-if="tasks.items.length" class="po-table-wrap"><table><thead><tr><th>任务 / 产品</th><th>交期</th><th>距交期</th><th>任务状态</th></tr></thead><tbody><tr v-for="task in tasks.items" :key="task.id"><td><RouterLink v-if="safeHref(task.href)" :to="task.href">{{ taskName(task) }}</RouterLink><strong v-else>{{ taskName(task) }}</strong><small>{{ task.task_number }}</small></td><td>{{ date(task.delivery_date) }}</td><td :class="{ 'po-danger': overdue(task) }">{{ dueText(task) }}</td><td>{{ task.status_display }}</td></tr></tbody></table></div>
              <p v-else class="po-empty">当前筛选范围没有任务</p>
              <div class="po-foot"><span>展示 {{ tasks.items.length }} / {{ tasks.total }} 单；历史逾期未并入未来日期柱形。</span><RouterLink to="/production-tasks">任务列表</RouterLink></div>
            </template>
          </div><p v-else class="po-empty">{{ message(data.sections.tasks, '当前范围没有交期任务') }}</p>
        </template>

        <template v-else-if="module.key === 'production'">
          <div v-if="leadTask" class="po-content">
            <div v-for="task in activeModule === 'production' ? tasks!.items : [leadTask]" :key="task.id" class="po-task">
              <div class="po-task-top"><div><RouterLink v-if="activeModule && safeHref(task.href)" :to="task.href" class="po-task-name">{{ taskName(task) }}</RouterLink><strong v-else class="po-task-name">{{ taskName(task) }}</strong><small>{{ task.task_number }}</small></div><span class="po-tag" :class="{ 'is-danger': overdue(task) }">{{ dueText(task) }}</span></div>
              <p class="po-task-quantity"><span v-for="product in activeModule ? task.products : task.products.slice(0, 2)" :key="product.id">{{ product.name }} {{ quantity(product.quantity) }} {{ product.unit }}</span><span v-if="!activeModule && task.products.length > 2">等 {{ task.products.length }} 种产品</span></p>
              <div class="po-progress-grid"><ProductionProgress v-for="stage in stages" :key="stage[0]" :label="stage[1]" :status="task.stages[stage[0]].state" :percentage="task.stages[stage[0]].percent" :display="task.stages[stage[0]].label" :receipt="stage[0] === 'assembly'" /></div>
              <p v-if="activeModule" class="po-muted po-task-status">{{ task.status_display }} · {{ scheduleText(task) }}</p>
            </div>
            <div v-if="activeModule" class="po-foot"><span>展示 {{ tasks!.items.length }} / {{ tasks!.total }} 单；各阶段独立统计，入库不等于交货。</span><RouterLink to="/production-tasks">全部任务</RouterLink></div>
            <p v-else class="po-note">{{ tasks!.items.length > 1 ? `还有 ${tasks!.items.length - 1} 单已加载任务，展开查看` : '工序分别统计 · 裁缝汇总含裁剪' }}</p>
          </div><p v-else class="po-empty">{{ message(data.sections.tasks, '当前范围没有生产任务') }}</p>
        </template>

        <template v-else-if="module.key === 'outsourcing'">
          <div v-if="outsourcing" class="po-content">
            <div class="po-summary"><strong class="po-number">{{ outsourcing.pending_count }}<small>单待回</small></strong><span v-if="outsourcing.overdue_count" class="po-tag is-danger">{{ outsourcing.overdue_count }} 单逾期</span></div>
            <div v-if="!activeModule" class="po-list"><div v-for="item in outsourcing.items.slice(0, 2)" :key="item.row_key" class="po-list-row"><div><strong>{{ item.factory_names.join('、') || item.order_number }}</strong><small>{{ item.order_number }} · {{ date(item.delivery_date) }}</small></div><span class="po-tag" :class="{ 'is-danger': outsourceLate(item.delivery_date) }">{{ outsourceLate(item.delivery_date) ? '回货已逾期' : item.status_display }}</span></div><p v-if="!outsourcing.items.length" class="po-empty">当前范围没有待回货外发单</p></div>
            <template v-else><div v-if="outsourcing.items.length" class="po-table-wrap"><table><thead><tr><th>外发单 / 加工厂</th><th>预计回货</th><th>已回货量</th><th>状态</th></tr></thead><tbody><tr v-for="item in outsourcing.items" :key="item.row_key"><td><RouterLink v-if="safeHref(item.href)" :to="item.href">{{ item.order_number }}</RouterLink><strong v-else>{{ item.order_number }}</strong><small>{{ item.factory_names.join('、') || '厂家未填写' }}</small></td><td :class="{ 'po-danger': outsourceLate(item.delivery_date) }">{{ date(item.delivery_date) }}<small v-if="outsourceLate(item.delivery_date)">已逾期</small></td><td><span v-for="(amount, index) in item.quantities" :key="index" class="po-amount">{{ amount.name }} {{ quantity(amount.quantity) }} {{ amount.unit }}</span><span v-if="!item.quantities.length">—</span><small v-if="item.receipt_state === 'UNKNOWN'">回货数量待核实</small><small v-if="item.receipt_state === 'MISSING'">回货凭证待核实</small></td><td>{{ item.status_display }}</td></tr></tbody></table></div><p v-else class="po-empty">当前范围没有待回货外发单</p><div class="po-foot"><span>展示 {{ outsourcing.items.length }} / {{ outsourcing.total }} 单；外发原料与加工件数量不相减。</span><RouterLink to="/workshop/outsourcing">外发列表</RouterLink></div></template>
          </div><p v-else class="po-empty">{{ message(data.sections.outsourcing, '暂无外发回货记录') }}</p>
        </template>

        <template v-else-if="module.key === 'output'">
          <div v-if="receipts" class="po-content">
            <p class="po-muted">{{ date(data.filters.production_date) }} · 按产品和单位分别查看</p>
            <div class="po-products"><div v-for="(amount, index) in activeModule ? receipts.today_quantities : receipts.today_quantities.slice(0, 2)" :key="index"><span>{{ amount.name || '成品' }}</span><strong>{{ quantity(amount.quantity) }}<small>{{ amount.unit }}</small></strong></div></div>
            <p class="po-note">当日 {{ receipts.today_count }} 笔成品入库<span v-if="!activeModule && receipts.today_quantities.length > 2"> · 另有 {{ receipts.today_quantities.length - 2 }} 项产品数量</span></p>
            <template v-if="activeModule"><div v-if="receipts.items.length" class="po-table-wrap"><table><thead><tr><th>产品 / 入库单</th><th>业务日期</th><th>入库数量</th></tr></thead><tbody><tr v-for="item in receipts.items" :key="item.id"><td><RouterLink v-if="safeHref(item.href)" :to="item.href">{{ item.name }}</RouterLink><strong v-else>{{ item.name }}</strong><small>{{ item.number }}</small></td><td>{{ date(item.date) }}</td><td>{{ quantity(item.quantity) }} {{ item.unit }}</td></tr></tbody></table></div><p v-else class="po-empty">当日没有成品入库记录</p><div class="po-foot"><span>展示 {{ receipts.items.length }} / {{ receipts.total }} 笔</span><RouterLink to="/inventory/finished-goods?tab=records">入库记录</RouterLink></div></template>
          </div><p v-else class="po-empty">{{ message(data.sections.receipts, '当日没有入库记录') }}</p>
          <section v-if="activeModule === 'output'" class="po-receipt-gaps" data-testid="production-receipt-gaps"><h3>成品入库待跟进</h3><p v-if="receipts?.pending_state === 'FORBIDDEN'" class="po-empty">没有查看入库差额所需的任务权限</p><template v-else-if="receipts?.pending_products.length"><div v-for="item in receipts.pending_products" :key="item.product_line_id" class="po-list-row"><div><RouterLink v-if="safeHref(item.href)" :to="item.href">{{ item.name }}</RouterLink><strong v-else>{{ item.name }}</strong><small>{{ item.task_number }} · 已入库 {{ quantity(item.received) }} {{ item.unit }}</small><small v-if="item.state === 'UNKNOWN'">数量与单位口径待核实</small></div><span>{{ quantity(item.remaining) }} {{ item.unit }}<small>待入库差额</small></span></div><p class="po-note">差额不代表已经完工。</p></template><p v-else class="po-empty">{{ receipts?.pending_state === 'UNKNOWN' ? '部分入库数量与单位口径待核实' : message(data.sections.receipts, '当前范围暂无成品入库差额') }}</p></section>
        </template>
      </article>
    </div>
    <p class="po-caption" aria-live="polite">{{ activeTitle ? `正在查看${activeTitle}；底部切换模块，按 Esc 或收起返回概览。` : '选择模块展开详情，关闭后回到原来的位置。' }}</p>
  </section>
</template>

<style scoped lang="scss" src="./productionOverview.scss" />
