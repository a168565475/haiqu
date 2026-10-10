<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  snapshot: Record<string, unknown>
  editable?: boolean
  title?: string
}>(), {
  editable: false,
  title: '卖方主体',
})

const emit = defineEmits<{ edit: [] }>()

const config = computed<Record<string, unknown>>(() => {
  const nested = props.snapshot.template_config
  return nested && typeof nested === 'object' ? nested as Record<string, unknown> : props.snapshot
})
const text = (key: string) => String(config.value[key] || '').trim()
const companyName = computed(() => text('seller_company_name') || text('legal_name'))
const contact = computed(() => [text('seller_contact_person'), text('seller_phone'), text('seller_email')].filter(Boolean).join(' · '))
const address = computed(() => text('seller_address'))
const missing = computed(() => !companyName.value)
</script>

<template>
  <section class="seller-card" :class="{ editable, missing }">
    <header>
      <div>
        <small>{{ title }}</small>
        <el-tag v-if="missing" type="danger" size="small">资料缺失</el-tag>
        <el-tag v-else-if="editable" type="warning" size="small">可编辑</el-tag>
        <el-tag v-else type="info" size="small">只读快照</el-tag>
      </div>
      <el-button v-if="editable" link type="primary" @click="emit('edit')">编辑卖方资料</el-button>
    </header>
    <strong>{{ companyName || '卖方公司名称待维护' }}</strong>
    <p>{{ contact || '联系人、电话或邮箱待维护' }}</p>
    <p>{{ address || '卖方地址待维护' }}</p>
    <footer>固定模板 HAIQU_FIXED_BILINGUAL · 责任角色：业务资料维护人员</footer>
  </section>
</template>

<style lang="scss" scoped>
.seller-card{display:grid;min-height:184px;padding:16px;border:1px solid #e4e4e7;border-radius:8px;background:#fff;gap:9px}.seller-card.editable{border-color:#93c5fd;background:#f8fbff}.seller-card.missing{border-color:#fecaca;background:#fffafa}.seller-card header{display:flex;align-items:center;justify-content:space-between;gap:12px}.seller-card header>div{display:flex;align-items:center;gap:8px}.seller-card small{color:#71717a;font-size:12px}.seller-card strong{font-size:16px;line-height:24px}.seller-card p{margin:0;color:#52525b;font-size:12px;line-height:18px}.seller-card footer{align-self:end;padding-top:8px;border-top:1px solid #e4e4e7;color:#8a8a93;font-size:11px}
</style>
