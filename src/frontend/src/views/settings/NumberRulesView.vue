<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'

import { fetchNumberRules } from '@/api/referenceData'
import type { NumberRule } from '@/types/referenceData'

const router = useRouter()
const loading = ref(false)
const errorMessage = ref('')
const rules = ref<NumberRule[]>([])

const configuredCount = computed(() => rules.value.filter((item) => item.is_configured).length)

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
  <section class="number-rules-page system-settings-theme">
    <nav class="crumb"><button type="button" @click="router.push({ name: 'reference-data-settings' })">系统配置</button><span>/</span><b>编号规则</b></nav>
    <header>
      <div><h1>编号规则</h1><p>登记现有业务编号格式和 PostgreSQL 序列；历史编号与当前流水不会重算或重置</p></div>
      <el-button :icon="Refresh" :loading="loading" @click="loadRules">刷新</el-button>
    </header>
    <div class="metrics"><article><span>已登记类型</span><strong>{{ rules.length }}</strong></article><article><span>已配置生成</span><strong>{{ configuredCount }}</strong></article><article><span>流水重置策略</span><strong>从不重置</strong></article></div>
    <el-alert title="规则当前为只读登记" description="修改前缀、日期段或位数会影响新编号，必须另行完成并发与历史兼容评审；本页不会直接改写数据库序列。" type="warning" :closable="false" show-icon />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false"><template #default><el-button size="small" @click="loadRules">重试</el-button></template></el-alert>
    <el-card v-else shadow="never" class="table-card">
      <el-table v-loading="loading" :data="rules" empty-text="暂无编号规则">
        <el-table-column prop="chinese_name" label="业务类型" min-width="120"><template #default="{ row }"><b>{{ row.chinese_name }}</b><small>{{ row.number_type }}</small></template></el-table-column>
        <el-table-column label="格式示例" min-width="190"><template #default="{ row }"><code>{{ formatExample(row) }}</code></template></el-table-column>
        <el-table-column prop="sequence_name" label="PostgreSQL 序列" min-width="230"><template #default="{ row }">{{ row.sequence_name || '—' }}</template></el-table-column>
        <el-table-column label="日期段" width="100"><template #default="{ row }">{{ dateGranularityLabel(row.date_granularity) }}</template></el-table-column>
        <el-table-column prop="sequence_padding" label="流水位数" width="90" />
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag class="settings-tag" :type="row.is_configured ? 'success' : 'info'">{{ row.is_configured ? '已配置' : '待确认' }}</el-tag></template></el-table-column>
      </el-table>
    </el-card>
  </section>
</template>

<style scoped lang="scss">
.number-rules-page{min-width:0;color:#1d2129}.crumb{display:flex;gap:8px;align-items:center;margin-bottom:14px;color:#86909c;font-size:13px}.crumb button{padding:0;border:0;color:#4e5969;background:none;cursor:pointer}.number-rules-page header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px}.number-rules-page h1{margin:0;font-size:28px}.number-rules-page header p{margin:8px 0 0;color:#86909c}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:16px}.metrics article{padding:18px;border:1px solid #e5e6eb;border-radius:8px;background:#fff}.metrics span,.table-card small{display:block;color:#86909c;font-size:12px}.metrics strong{display:block;margin-top:8px;font-size:24px}.table-card{margin-top:16px}.table-card b{display:block}.table-card code{color:#1d2129;font-family:Consolas,monospace}@media(max-width:760px){.metrics{grid-template-columns:1fr}.number-rules-page header{gap:12px;flex-direction:column}}
</style>
