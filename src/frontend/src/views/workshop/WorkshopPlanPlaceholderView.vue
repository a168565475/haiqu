<script setup lang="ts">
import { computed } from 'vue'
import { Calendar } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const planTitle = computed(() => String(route.meta.planTitle || '生产计划'))
</script>

<template>
  <section class="plan-page" data-testid="workshop-plan-page">
    <header class="plan-page__heading">
      <p>生产车间</p>
      <h1>{{ planTitle }}</h1>
      <span>计划入口已建立，排产规则和数据来源尚待确认。</span>
    </header>

    <div class="plan-page__empty">
      <span class="plan-page__icon" aria-hidden="true"><Calendar /></span>
      <ElTag type="info" effect="plain">功能待定义</ElTag>
      <h2>{{ planTitle }}暂未启用</h2>
      <p>在确认订单来源、计划日期、产能、人员设备和调整规则之前，本页不会生成或保存生产计划。</p>
    </div>
  </section>
</template>

<style scoped lang="scss">
.plan-page {
  min-width: 1450px;
  min-height: calc(100vh - 56px);
  padding: 30px 36px 40px;
  color: #172033;
  background: var(--erp-page-background);
}

.plan-page__heading p {
  margin: 0;
  color: #409eff;
  font-size: 13px;
}

.plan-page__heading h1 {
  margin: 5px 0 4px;
  font-size: 30px;
  line-height: 40px;
}

.plan-page__heading > span {
  color: #7b8495;
  font-size: 14px;
}

.plan-page__empty {
  min-height: 420px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  margin-top: 22px;
  padding: 48px 56px;
  border: 1px solid #e4e7ed;
  border-radius: 12px;
  background: #fff;
}

.plan-page__icon {
  width: 58px;
  height: 58px;
  display: grid;
  margin-bottom: 20px;
  border-radius: 12px;
  color: #337ecc;
  background: #ecf5ff;
  place-content: center;
}

.plan-page__icon :deep(svg) {
  width: 30px;
  height: 30px;
}

.plan-page__empty h2 {
  margin: 18px 0 8px;
  font-size: 22px;
}

.plan-page__empty p {
  max-width: 680px;
  margin: 0;
  color: #606b7d;
  font-size: 14px;
  line-height: 1.8;
}
</style>
