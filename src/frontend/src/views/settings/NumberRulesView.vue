<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { Refresh } from '@element-plus/icons-vue'

import { fetchNumberRules } from '@/api/referenceData'
import type { NumberRule } from '@/types/referenceData'

const loading = ref(false)
const errorMessage = ref('')
const rules = ref<NumberRule[]>([])

function formatExample(rule: NumberRule): string {
  if (!rule.is_configured) return '未配置'
  const date = rule.date_granularity === 'MONTH' ? '202608' : rule.date_granularity === 'YEAR' ? '2026' : ''
  return rule.format_pattern
    .replace('{prefix}', rule.prefix)
    .replace('{date}', date)
    .replace('{sequence}', '1'.padStart(rule.sequence_padding, '0'))
}

function dateGranularityLabel(value: NumberRule['date_granularity']): string {
  return { NONE: '无', YEAR: '年份', MONTH: '年月' }[value]
}

async function loadRules() {
  loading.value = true
  errorMessage.value = ''
  try {
    rules.value = (await fetchNumberRules()).data
  } catch {
    errorMessage.value = '编号规则加载失败，请检查网络或查看权限后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(loadRules)
</script>

<template>
  <section class="number-rules-page system-settings-theme erp-glass-list">
    <section v-glass-spotlight class="erp-list-filter"><header class="erp-list-heading">
      <div><h1>编号规则</h1></div>
      <el-button class="erp-button-motion" :icon="Refresh" :loading="loading" @click="loadRules">刷新</el-button>
    </header></section>
    <el-alert title="规则当前为只读登记" description="修改前缀、日期段或位数会影响新编号，必须另行完成并发与历史兼容评审；本页不会直接改写数据库序列。" type="warning" :closable="false" show-icon />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false"><template #default><el-button size="small" @click="loadRules">重试</el-button></template></el-alert>
    <section v-else class="table-card erp-list-data"><div class="erp-list-table-frame">
      <el-table height="100%" v-loading="loading" :data="rules" empty-text="暂无编号规则">
        <el-table-column prop="chinese_name" label="业务类型" min-width="120"><template #default="{ row }"><b>{{ row.chinese_name }}</b><small>{{ row.number_type }}</small></template></el-table-column>
        <el-table-column label="格式示例" min-width="190"><template #default="{ row }"><code>{{ formatExample(row) }}</code></template></el-table-column>
        <el-table-column prop="sequence_name" label="PostgreSQL 序列" min-width="230"><template #default="{ row }">{{ row.sequence_name || '—' }}</template></el-table-column>
        <el-table-column label="日期段" width="100"><template #default="{ row }">{{ dateGranularityLabel(row.date_granularity) }}</template></el-table-column>
        <el-table-column prop="sequence_padding" label="流水位数" width="90" />
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag class="settings-tag" :type="row.is_configured ? 'success' : 'info'">{{ row.is_configured ? '已配置' : '待确认' }}</el-tag></template></el-table-column>
      </el-table>
    </div></section>
  </section>
</template>

<style scoped lang="scss">
.table-card b { display: block; }
.table-card code { color: var(--erp-table-text); font-family: Consolas, monospace; }
</style>
