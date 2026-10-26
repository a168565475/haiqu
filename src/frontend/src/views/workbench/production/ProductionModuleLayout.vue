<script setup lang="ts">
import { computed, ref } from 'vue'
import { Close, FullScreen } from '@element-plus/icons-vue'
import { useModuleFocus, type OverviewModuleKey } from './useModuleFocus'

const props = defineProps<{
  modules: readonly { key: OverviewModuleKey; title: string; subtitle?: string; summary: string; area?: string }[]
  variant: 'owner' | 'workshop'
}>()
const root = ref<HTMLElement>()
const { activeModule, transitionTo, onKeydown, isAnimating } = useModuleFocus(root)
const otherModules = computed(() => props.modules.filter(module => module.key !== activeModule.value))
const activeTitle = computed(() => props.modules.find(module => module.key === activeModule.value)?.title)

function modulePosition(module: typeof props.modules[number]) {
  if (!activeModule.value) return { '--pml-area': module.area ?? module.key }
  if (module.key === activeModule.value) return { '--pml-area': '1 / 1 / 2 / -1', '--pml-compact-area': '1 / 1 / 2 / -1' }
  const index = otherModules.value.findIndex(item => item.key === module.key)
  return { '--pml-area': `2 / ${index + 1}`, '--pml-compact-area': `${2 + Math.floor(index / 2)} / ${1 + index % 2}` }
}

function openModule(key: OverviewModuleKey) {
  if (props.modules.some(module => module.key === key)) return transitionTo(key)
}
function openFromCard(event: MouseEvent, key: OverviewModuleKey) {
  if (event.target instanceof Element && event.target.closest('a, button, input, select, textarea')) return
  void openModule(key)
}
defineExpose({ openModule })
</script>

<template>
  <section ref="root" class="production-module-layout" :class="`pml--${variant}`" data-testid="production-module-layout" :data-active-module="activeModule || 'overview'" :data-animating="isAnimating" @keydown="onKeydown">
    <div class="pml-stage" :class="{ 'is-focused': activeModule }" :style="{ '--pml-columns': otherModules.length, '--pml-dock-rows': Math.ceil(otherModules.length / 2) }">
      <div v-if="activeModule" class="pml-dock" aria-hidden="true" />
      <article v-for="module in modules" :key="module.key" class="po-module pml-module" :class="{ 'is-detail': activeModule === module.key, 'is-mini': activeModule && activeModule !== module.key }" :data-module="module.key" :style="modulePosition(module)" :aria-label="module.title" @click="openFromCard($event, module.key)">
        <button v-if="activeModule && activeModule !== module.key" class="pml-mini-open" type="button" data-module-open :aria-label="`切换到${module.title}`" :aria-expanded="false" @click="openModule(module.key)" />
        <header class="pml-head">
          <div><h2>{{ module.title }}</h2><p v-if="module.subtitle && (!activeModule || activeModule === module.key)">{{ module.subtitle }}</p></div>
          <button v-if="activeModule === module.key" class="pml-action" type="button" data-module-close :aria-label="`收起${module.title}`" @click="transitionTo(null)"><Close aria-hidden="true" />收起</button>
          <button v-else-if="!activeModule" class="pml-action" type="button" data-module-open :aria-label="`展开${module.title}`" :aria-expanded="false" @click="openModule(module.key)"><FullScreen aria-hidden="true" />展开</button>
        </header>
        <div class="pml-body" :hidden="Boolean(activeModule && activeModule !== module.key)"><slot :name="module.key" :expanded="activeModule === module.key" /></div>
        <p v-if="activeModule && activeModule !== module.key" class="pml-summary">{{ module.summary }}</p>
      </article>
    </div>
    <p v-if="activeModule" class="pml-caption" aria-live="polite">正在查看{{ activeTitle }}；底部切换模块，按 Esc 或收起返回概览。</p>
  </section>
</template>

<style scoped lang="scss">
.production-module-layout {
  min-width: 0;
  container-type: inline-size;
  container-name: production-modules;
  .pml-stage { display: grid; grid-template-columns: minmax(0, 1.9fr) minmax(0, 1fr); grid-template-areas: 'production delivery' 'outsourcing todo'; gap: 14px; position: relative; isolation: isolate; }
  &.pml--workshop .pml-stage { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-areas: 'production production' 'output todo'; }
  .pml-stage.is-focused { grid-template-columns: repeat(var(--pml-columns), minmax(0, 1fr)); grid-template-rows: clamp(280px, var(--pml-detail-height, calc(100dvh - 560px)), 580px) 100px; grid-template-areas: none; }
  .pml-module { grid-area: var(--pml-area); position: relative; min-width: 0; min-height: 0; display: flex; flex-direction: column; border: 1px solid var(--erp-glass-border); border-radius: 15px; background: var(--erp-glass-background); box-shadow: var(--erp-glass-shadow); backdrop-filter: var(--erp-glass-backdrop); transform-origin: top left; }
  .pml-module.is-detail { z-index: 2; overflow: auto; overscroll-behavior: contain; }
  .pml-module.is-mini { z-index: 1; margin: 8px; border: 0; border-radius: 11px; background: var(--erp-glass-inner-background); box-shadow: none; justify-content: center; overflow: hidden; }
  .pml-module.is-mini:hover { background: var(--erp-color-hover); }
  .pml-dock { grid-area: 2 / 1 / 3 / -1; border: 1px solid var(--erp-glass-border); border-radius: 17px; background: var(--erp-glass-background); box-shadow: var(--erp-glass-shadow); backdrop-filter: var(--erp-glass-backdrop); }
  .pml-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex: none; padding: 18px 20px 14px; }
  .pml-head > div { min-width: 0; }
  .pml-head h2 { margin: 0; font-size: 16px; font-weight: 600; line-height: 24px; overflow-wrap: anywhere; }
  .pml-head p { margin: 5px 0 0; font-size: 12px; line-height: 18px; color: var(--erp-color-text-secondary); }
  .pml-action { display: inline-flex; align-items: center; justify-content: center; gap: 5px; flex: none; min-height: 32px; padding: 5px 9px; border: 1px solid var(--erp-color-border-subtle); border-radius: 8px; background: var(--erp-glass-inner-background); color: var(--erp-color-text-secondary); font: inherit; font-size: 12px; cursor: pointer; white-space: nowrap; }
  .pml-action:hover { color: var(--erp-color-brand); background: var(--erp-color-hover); }
  .pml-action svg { width: 14px; height: 14px; }
  .pml-action:focus-visible, .pml-mini-open:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
  .pml-mini-open { position: absolute; inset: 0; z-index: 2; width: 100%; height: 100%; padding: 0; border: 0; border-radius: inherit; background: transparent; cursor: pointer; }
  .pml-body { min-width: 0; padding: 0; }
  .pml-body[hidden] { display: none; }
  .is-detail .pml-head { position: sticky; top: 0; z-index: 1; padding-bottom: 14px; border-radius: 14px 14px 0 0; background: var(--erp-glass-inner-background); backdrop-filter: var(--erp-glass-backdrop); }
  .is-mini .pml-head { padding: 0 12px; }
  .is-mini .pml-head h2 { font-size: 12px; line-height: 18px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pml-summary { margin: 6px 0 0; padding: 0 12px; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 18px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .pml-caption { margin: 12px 0 0; font-size: 12px; line-height: 20px; color: var(--erp-color-text-secondary); }
  @container production-modules (max-width: 760px) {
    .pml-stage { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'production' 'delivery' 'outsourcing' 'todo'; }
    &.pml--workshop .pml-stage { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'production' 'output' 'todo'; }
    .pml-stage.is-focused { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: minmax(280px, 55dvh); grid-auto-rows: 84px; grid-template-areas: none; gap: 8px; }
    .pml-stage.is-focused .pml-module { grid-area: var(--pml-compact-area); }
    .pml-dock { grid-area: 2 / 1 / span var(--pml-dock-rows) / -1; }
    .pml-head { gap: 8px; }
    .pml-action { padding: 5px 7px; }
  }
}
</style>
