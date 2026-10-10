<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { checkCustomerDuplicates, createCustomer, fetchCustomerOptions } from '@/api/customers'
import { useAuthStore } from '@/stores/auth'
import type { CustomerDuplicateMatch, CustomerOptions } from '@/types/customer'

import {
  buildCustomerCreatePayload,
  createEmptyCustomerForm,
  customerRequestError,
  getDerivedCountryCode,
  getSecondaryRegions,
  validateCustomerCreateForm,
  type CustomerFormErrors,
} from './customerForm'

const router = useRouter()
const authStore = useAuthStore()
const canCreate = computed(() => authStore.hasPermission('customers.add_customeraccount'))

const form = reactive(createEmptyCustomerForm())
const options = ref<CustomerOptions | null>(null)
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const checkingDuplicate = ref(false)
const duplicateError = ref('')
const duplicateMatches = ref<CustomerDuplicateMatch[]>([])
const fieldErrors = reactive<CustomerFormErrors>({})
let duplicateTimer: ReturnType<typeof setTimeout> | undefined

const secondaryRegions = computed(() => getSecondaryRegions(options.value, form.primaryRegionId))
const countryCode = computed(() => getDerivedCountryCode(options.value, form.secondaryRegionId))
const highRiskMatches = computed(() => duplicateMatches.value.filter((item) => item.match_level === 'HIGH'))
const canCheckDuplicate = computed(() => form.accountName.trim().length >= 2 || form.website.trim().length >= 4)
const requiredCompleted = computed(() => [form.accountName.trim(), form.primaryRegionId, form.sourceId].filter(Boolean).length)

async function loadOptions() {
  loading.value = true
  loadError.value = ''
  try {
    options.value = await fetchCustomerOptions()
  } catch (error) {
    loadError.value = customerRequestError(error, '客户建档选项加载失败。')
  } finally {
    loading.value = false
  }
}

function clearFieldErrors() {
  for (const key of Object.keys(fieldErrors) as Array<keyof CustomerFormErrors>) {
    delete fieldErrors[key]
  }
}

async function focusFirstError(errors: CustomerFormErrors) {
  await nextTick()
  const firstKey = Object.keys(errors)[0]
  if (!firstKey) return
  const input = document.querySelector<HTMLElement>(`[data-field="${firstKey}"] input`)
  input?.focus()
}

function resetForm() {
  Object.assign(form, createEmptyCustomerForm())
  clearFieldErrors()
  duplicateMatches.value = []
  duplicateError.value = ''
}

async function runDuplicateCheck() {
  if (!canCheckDuplicate.value) {
    duplicateMatches.value = []
    duplicateError.value = ''
    return
  }
  checkingDuplicate.value = true
  duplicateError.value = ''
  try {
    const query = form.accountName.trim()
      ? { name: form.accountName.trim(), website: form.website.trim() || undefined }
      : { website: form.website.trim() }
    const result = await checkCustomerDuplicates({
      ...query,
      country_code: countryCode.value || undefined,
    })
    duplicateMatches.value = result.matches
  } catch (error) {
    duplicateMatches.value = []
    duplicateError.value = customerRequestError(error, '重复客户检查失败，请稍后重试。')
  } finally {
    checkingDuplicate.value = false
  }
}

function scheduleDuplicateCheck() {
  if (duplicateTimer) clearTimeout(duplicateTimer)
  duplicateTimer = setTimeout(() => void runDuplicateCheck(), 400)
}

async function submitCreate(continueCreating = false) {
  if (saving.value || !canCreate.value) return
  clearFieldErrors()
  const errors = validateCustomerCreateForm(form)
  Object.assign(fieldErrors, errors)
  if (Object.keys(errors).length) {
    ElMessage.warning('请检查标记的客户资料。')
    await focusFirstError(errors)
    return
  }

  saving.value = true
  try {
    const created = await createCustomer(buildCustomerCreatePayload(form, options.value))
    ElMessage.success('客户已创建。')
    if (continueCreating) {
      resetForm()
      window.scrollTo({ top: 0, behavior: 'smooth' })
      return
    }
    await router.push({ name: 'customer-detail', params: { customerId: created.data.id } })
  } catch (error) {
    ElMessage.error(customerRequestError(error, '客户创建失败，请检查资料后重试。'))
  } finally {
    saving.value = false
  }
}

function openExistingCustomer(customerId: string) {
  void router.push({ name: 'customer-detail', params: { customerId } })
}

watch(() => [form.accountName, form.website, form.secondaryRegionId], scheduleDuplicateCheck)
watch(() => form.primaryRegionId, (current, previous) => {
  if (previous && current !== previous) form.secondaryRegionId = ''
})
watch(form, () => clearFieldErrors(), { deep: true })

onMounted(() => {
  if (canCreate.value) void loadOptions()
  else loading.value = false
})
onBeforeUnmount(() => {
  if (duplicateTimer) clearTimeout(duplicateTimer)
})
</script>

<template>
  <main class="customer-create-page" data-customer-create-page>
    <header class="form-page-header">
      <div class="title-block">
        <p>客户管理 / 客户列表 / 新建客户</p>
        <div class="title-line">
          <h1>新建客户</h1>
          <span>实时查重</span>
        </div>
        <small>先录入关键资料；创建后进入客户 360 继续完善主体、地址与客户属性。</small>
      </div>
      <div class="header-actions">
        <ElButton @click="router.push({ name: 'customers' })">取消</ElButton>
        <ElButton :loading="saving" :disabled="loading || Boolean(loadError) || !canCreate" @click="submitCreate(true)">继续创建</ElButton>
        <ElButton type="primary" :loading="saving" :disabled="loading || Boolean(loadError) || !canCreate" @click="submitCreate(false)">创建客户</ElButton>
      </div>
    </header>

    <section v-if="!canCreate" class="page-state">
      <ElResult icon="warning" title="无权新建客户" sub-title="当前账号缺少新建客户权限，请联系管理员。">
        <template #extra><ElButton @click="router.push({ name: 'customers' })">返回客户列表</ElButton></template>
      </ElResult>
    </section>

    <section v-else-if="loading" class="page-state page-state--loading" aria-busy="true">
      <ElSkeleton :rows="10" animated />
    </section>

    <section v-else-if="loadError" class="page-state">
      <ElResult icon="error" title="无法打开新建客户页面" :sub-title="loadError">
        <template #extra><ElButton type="primary" @click="loadOptions">重新加载</ElButton></template>
      </ElResult>
    </section>

    <section v-else class="create-workspace">
      <aside class="create-section-nav" aria-label="新建流程">
        <p class="nav-heading">新建流程</p>
        <div class="required-progress">
          <div><span>必填项</span><strong>{{ requiredCompleted }} / 3</strong></div>
          <ElProgress :percentage="requiredCompleted / 3 * 100" :show-text="false" :stroke-width="4" />
        </div>
        <ol class="create-steps">
          <li class="is-active"><span>01</span><strong>基础资料</strong></li>
          <li><span>02</span><strong>初始联系人</strong></li>
          <li><span>03</span><strong>重复校验</strong></li>
        </ol>
        <div class="create-scope">
          <strong>本页仅录入创建所需资料</strong>
          <p>主体、地址、客户类型、等级、标签等资料将在创建后进入客户 360 完善。</p>
        </div>
      </aside>

      <ElForm label-position="top" class="create-form" :model="form" @submit.prevent>
        <div class="section-heading">
          <strong>客户基础资料</strong>
          <span>{{ checkingDuplicate ? '正在自动查重' : '输入客户名称或网站后自动查重' }}</span>
        </div>

        <div class="create-form-grid">
          <ElFormItem label="客户名称" required :error="fieldErrors.accountName" data-field="accountName">
            <ElInput v-model="form.accountName" maxlength="250" placeholder="输入公司或客户名称" />
          </ElFormItem>
          <ElFormItem label="网站 / 域名" :error="fieldErrors.website" data-field="website">
            <ElInput v-model="form.website" maxlength="500" placeholder="例如 example.com" />
          </ElFormItem>
          <ElFormItem label="一级地区" required :error="fieldErrors.primaryRegionId" data-field="primaryRegionId">
            <ElSelect v-model="form.primaryRegionId" filterable placeholder="请选择一级地区">
              <ElOption v-for="item in options?.primary_regions" :key="item.id" :label="item.region_name" :value="item.id" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="二级地区" data-field="secondaryRegionId">
            <ElSelect v-model="form.secondaryRegionId" filterable clearable :disabled="!form.primaryRegionId" placeholder="可不填写">
              <ElOption v-for="item in secondaryRegions" :key="item.id" :label="item.region_name" :value="item.id" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="客户来源" required :error="fieldErrors.sourceId" data-field="sourceId">
            <ElSelect v-model="form.sourceId" filterable placeholder="请选择客户来源">
              <ElOption v-for="item in options?.customer_sources" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="国家代码" data-field="countryCode">
            <ElInput :model-value="countryCode ? `${countryCode} · 由二级地区自动带出` : '由二级地区自动带出'" disabled />
          </ElFormItem>
        </div>

        <div v-if="highRiskMatches.length" class="inline-duplicate-alert" role="alert">
          <span class="inline-duplicate-alert__icon" aria-hidden="true"><svg viewBox="0 0 16 16" focusable="false"><path d="M8 1.5 14.2 13H1.8L8 1.5Z" /><path d="M8 5.2v3.2M8 10.8h.01" /></svg></span><span>当前输入触发 {{ highRiskMatches.length }} 条高匹配记录；请在右侧确认后选择已有客户或继续创建。</span>
        </div>
        <div v-else-if="duplicateError" class="inline-duplicate-alert is-error" role="alert">
          <span class="inline-duplicate-alert__icon" aria-hidden="true"><svg viewBox="0 0 16 16" focusable="false"><circle cx="8" cy="8" r="6.25" /><path d="M8 5v3.2M8 10.8h.01" /></svg></span><span>{{ duplicateError }}</span>
        </div>
        <div v-else class="inline-duplicate-alert is-clear">
          <span class="inline-duplicate-alert__icon" aria-hidden="true"><svg viewBox="0 0 16 16" focusable="false"><path d="m3.2 8.3 3 3L12.8 4.8" /></svg></span><span>{{ canCheckDuplicate && !checkingDuplicate ? '未发现高匹配客户，可以继续创建。' : '输入客户名称或网站后开始实时查重。' }}</span>
        </div>

        <div class="section-divider" />
        <div class="section-heading contact-heading">
          <strong>初始联系人</strong>
          <span>可选 · 填写联系方式时必须同时填写姓名</span>
        </div>
        <div class="create-form-grid contact-grid">
          <ElFormItem label="联系人姓名" :error="fieldErrors.contactName" data-field="contactName">
            <ElInput v-model="form.contactName" maxlength="150" placeholder="可稍后补充" />
          </ElFormItem>
          <ElFormItem label="邮箱 / 电话" :error="fieldErrors.contactMethod" data-field="contactMethod">
            <ElInput v-model="form.contactMethod" maxlength="255" placeholder="输入邮箱或电话号码" />
          </ElFormItem>
        </div>
        <div class="completion-hint">
          <strong>创建后继续完善</strong>
          <p>法定主体、地址、客户类型、客户等级、行业、感兴趣产品与标签不在首次建档时录入，避免首次建档路径过长。</p>
        </div>
      </ElForm>

      <aside class="create-context" aria-label="重复检查与创建说明">
        <section v-if="duplicateMatches.length" class="context-card duplicate-card">
          <header><strong>发现 {{ duplicateMatches.length }} 个匹配客户</strong><span>{{ duplicateMatches[0]?.match_score }}% {{ duplicateMatches[0]?.match_level === 'HIGH' ? '高匹配' : '中匹配' }}</span></header>
          <p>客户名称或网站与已有记录相似，请先确认是否为同一客户。</p>
          <article v-for="match in duplicateMatches.slice(0, 3)" :key="match.customer_id" class="duplicate-match">
            <strong>{{ match.account_name }}</strong>
            <span>{{ match.account_code }} · {{ match.primary_country_code || '国家未知' }} · {{ match.lifecycle_stage }}</span>
            <small>{{ match.primary_website_url || '未登记网站' }}</small>
            <div>
              <ElButton type="primary" @click="openExistingCustomer(match.customer_id)">选择已有客户</ElButton>
              <ElButton @click="openExistingCustomer(match.customer_id)">查看详情</ElButton>
            </div>
          </article>
        </section>
        <section v-else class="context-card duplicate-card duplicate-card--empty" :aria-busy="checkingDuplicate">
          <strong>实时重复校验</strong>
          <p v-if="checkingDuplicate">正在检查客户名称、网站和国家信息…</p>
          <p v-else-if="duplicateError">{{ duplicateError }}</p>
          <p v-else>输入客户名称或网站后，系统会在这里显示真实匹配结果。</p>
        </section>

        <section class="context-card result-card">
          <h2>创建后系统会同步完成</h2>
          <ul>
            <li>建立客户主档与客户编号</li>
            <li>记录客户来源并保留历史</li>
            <li>将当前业务员设为负责人</li>
            <li>创建一条初始活跃度记录</li>
          </ul>
        </section>
        <section class="context-card rule-card">
          <h2>创建规则</h2>
          <p>填写联系方式时，必须同时填写联系人姓名；客户名称、一级地区、客户来源为必填。</p>
        </section>
      </aside>
    </section>
  </main>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use './customer-form-shared' as shared;

.customer-create-page {
  width: 100%;
  height: calc(100dvh - 64px);
  min-height: 760px;
  overflow: hidden;
  color: token.$crm-text-primary;
  background: token.$crm-color-page;
  font-family: token.$crm-font-body;
  @include shared.crm-buttons;
}

.form-page-header {
  height: 104px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  border-bottom: 1px solid token.$crm-border-default;
  background: token.$crm-color-surface;
}

.title-block { height: 83px; padding-top: 1px; }
.title-block > p { margin: 0; color: token.$crm-text-muted; font-size: 11px; line-height: 20px; }
.title-line { height: 38px; display: flex; align-items: center; gap: 12px; }
.title-line h1 { margin: 0; font-family: token.$crm-font-display; font-size: 28px; font-weight: 700; line-height: 33px; letter-spacing: -0.02em; }
.title-line span { height: 28px; display: inline-flex; align-items: center; padding: 0 10px; border-radius: token.$crm-radius-pill; color: token.$crm-primary; background: token.$crm-danger-soft; font-size: 12px; font-weight: 500; }
.title-block > small { display: block; color: token.$crm-text-muted; font-size: 11px; line-height: 20px; }
.header-actions { display: flex; gap: 8px; }
.header-actions :deep(.el-button:first-child) { width: 58px; padding: 0; }
.header-actions :deep(.el-button:nth-child(2)),
.header-actions :deep(.el-button:nth-child(3)) { width: 84px; padding: 0; }

.page-state { height: calc(100% - 104px); display: grid; place-items: center; padding: 48px; background: token.$crm-color-surface; }
.page-state--loading { display: block; }
.page-state--loading :deep(.el-skeleton) { max-width: 1200px; margin: 40px auto; }

.create-workspace {
  height: calc(100% - 104px);
  display: grid;
  grid-template-columns: 196px minmax(0, 1000px) 406px;
  gap: 20px;
  padding: 24px;
  overflow: hidden;
  background: token.$crm-color-page;
}

.create-section-nav,
.create-form,
.create-context { height: 100%; min-height: 0; }
.create-section-nav { overflow: hidden; background: token.$crm-color-surface; }
.nav-heading { height: 32px; margin: 0; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.required-progress { height: 60px; padding: 14px; background: token.$crm-color-subtle; }
.required-progress > div { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.required-progress strong { color: token.$crm-success; }
.required-progress :deep(.el-progress-bar__outer) { background: token.$crm-border-default; }
.required-progress :deep(.el-progress-bar__inner) { background: token.$crm-success; }
.create-steps { display: flex; flex-direction: column; gap: 10px; margin: 10px 0 0; padding: 0 0 10px; border-bottom: 1px solid token.$crm-border-default; list-style: none; }
.create-steps li { height: 42px; display: flex; align-items: center; gap: 10px; padding: 0 12px; border-radius: token.$crm-radius-3; color: token.$crm-text-secondary; font-size: 13px; }
.create-steps li > span { width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%; background: token.$crm-color-subtle; color: token.$crm-text-muted; font-size: 11px; }
.create-steps li.is-active { color: token.$crm-text-primary; background: token.$crm-success-soft; }
.create-steps li.is-active > span { color: token.$crm-success; }
.create-scope { height: 110px; padding: 12px 10px; color: token.$crm-text-secondary; }
.create-scope strong { font-size: 12px; line-height: 20px; }
.create-scope p { margin: 6px 0 0; font-size: 11px; line-height: 20px; }

.create-form {
  box-sizing: border-box;
  overflow: hidden;
  padding: 24px;
  border: 1px solid token.$crm-border-default;
  border-radius: 8px;
  background: token.$crm-color-surface;
  @include shared.element-form-controls(32px, 12px, 13px, 7px);
}
.section-heading { height: 32px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.section-heading strong { position: relative; padding-left: 13px; font-size: 16px; line-height: 24px; }
.section-heading strong::before { position: absolute; top: 2px; bottom: 2px; left: 0; width: 3px; border-radius: 2px; background: token.$crm-primary; content: ''; }
.section-heading span { color: token.$crm-text-muted; font-size: 12px; line-height: 20px; }
.create-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; }
.create-form-grid :deep(.el-form-item) { height: 60px; }
.inline-duplicate-alert { min-height: 48px; height: auto; box-sizing: border-box; display: flex; align-items: center; gap: 8px; margin-top: 20px; padding: 12px; border: 1px solid token.$crm-border-default; border-radius: token.$crm-radius-2; color: token.$crm-text-regular; background: token.$crm-warning-soft; font-size: 13px; font-weight: 400; line-height: 20px; }
.inline-duplicate-alert__icon { display: inline-flex; width: 16px; height: 16px; flex: none; align-items: center; justify-content: center; color: token.$crm-warning; }
.inline-duplicate-alert__icon svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.5; }
.inline-duplicate-alert > span:last-child { min-width: 0; }
.inline-duplicate-alert.is-clear { background: token.$crm-success-soft; }
.inline-duplicate-alert.is-clear .inline-duplicate-alert__icon { color: token.$crm-success; }
.inline-duplicate-alert.is-error { background: token.$crm-danger-soft; }
.inline-duplicate-alert.is-error .inline-duplicate-alert__icon { color: token.$crm-danger; }
.section-divider { height: 1px; margin: 16px 0; background: token.$crm-border-default; }
.contact-heading { margin-bottom: 16px; }
.contact-grid { row-gap: 0; }
.completion-hint { height: 98px; margin-top: 20px; padding: 16px; border-radius: 7px; background: token.$crm-color-subtle; }
.completion-hint strong { font-size: 13px; line-height: 21px; }
.completion-hint p { margin: 7px 0 0; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }

.create-context { display: flex; flex-direction: column; gap: 16px; overflow: hidden; background: token.$crm-color-surface; }
.context-card { padding: 18px; border: 1px solid token.$crm-border-default; border-radius: 8px; background: token.$crm-color-surface; }
.duplicate-card { min-height: 130px; border-color: token.$crm-warning-border; background: token.$crm-warning-soft; }
.duplicate-card > header { height: 26px; display: flex; align-items: center; justify-content: space-between; }
.duplicate-card > header strong, .duplicate-card--empty > strong { font-size: 15px; line-height: 23px; }
.duplicate-card > header span { padding: 3px 9px; border-radius: token.$crm-radius-pill; color: token.$crm-text-inverse; background: token.$crm-warning; font-size: 11px; line-height: 20px; }
.duplicate-card > p { margin: 12px 0; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.duplicate-match { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; padding: 14px; border: 1px solid token.$crm-warning; border-radius: 7px; background: token.$crm-color-surface; }
.duplicate-match > strong { font-size: 14px; line-height: 22px; }
.duplicate-match > span { color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.duplicate-match > small { color: token.$crm-text-muted; font-size: 12px; line-height: 20px; }
.duplicate-match > div { display: flex; gap: 8px; margin-top: 4px; }
.duplicate-card--empty { min-height: 160px; }
.result-card { min-height: 187px; }
.rule-card { min-height: 130px; background: token.$crm-color-subtle; }
.context-card h2 { margin: 0; font-size: 14px; line-height: 22px; }
.result-card h2 { font-size: 15px; line-height: 23px; }
.result-card ul { display: flex; flex-direction: column; gap: 12px; margin: 12px 0 0; padding: 0; list-style: none; }
.result-card li { position: relative; padding-left: 15px; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.result-card li::before { position: absolute; top: 7px; left: 0; width: 6px; height: 6px; border-radius: 50%; background: token.$crm-success; content: ''; }
.rule-card p { margin: 12px 0 0; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }

/* 按客诉新建原型重排为居中的双栏操作面板。 */
.customer-create-page {
  position: relative;
  width: min(1180px, calc(100% - 56px));
  height: min(850px, calc(100dvh - 140px));
  min-height: 0;
  margin: 24px auto;
  border: 1px solid token.$crm-border-default;
  border-radius: 6px;
  background: token.$crm-color-surface;
  box-shadow: 0 18px 46px rgb(43 37 31 / 14%);
}

.customer-create-page::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 0;
  height: 72px;
  border-top: 1px solid token.$crm-border-default;
  background: token.$crm-color-surface;
  content: '';
}

.form-page-header {
  height: 76px;
  padding: 0 30px;
}

.title-block {
  height: auto;
  padding: 0;
}

.title-block > p,
.title-block > small {
  display: none;
}

.title-line {
  height: auto;
}

.title-line h1 {
  font-size: 28px;
  font-weight: 600;
  line-height: 34px;
}

.title-line span {
  height: 24px;
  border-radius: token.$crm-radius-pill;
  font-size: 12px;
}

.header-actions {
  position: absolute;
  right: 30px;
  bottom: 15px;
  z-index: 2;
  gap: 10px;
}

.header-actions :deep(.el-button) {
  min-width: 88px;
  height: 32px;
  margin: 0;
  border-radius: token.$crm-radius-2;
}

.header-actions :deep(.el-button:nth-child(3)) {
  min-width: 104px;
}

.create-workspace {
  height: calc(100% - 148px);
  grid-template-columns: 1fr 1fr;
  gap: 0;
  padding: 0;
  background: token.$crm-color-surface;
}

.create-section-nav {
  display: none;
}

.create-form {
  padding: 24px 30px;
  overflow-y: auto;
  border: 0;
  border-radius: 0;
  @include shared.element-form-controls(32px, 12px, 13px, 7px);
}

.create-form-grid {
  gap: 10px 16px;
}

.create-form-grid :deep(.el-form-item) {
  height: 60px;
}

.section-heading {
  margin-bottom: 12px;
}

.section-heading strong {
  padding-left: 0;
  font-family: token.$crm-font-display;
  font-size: 19px;
  font-weight: 600;
}

.section-heading strong::before {
  display: none;
}

.section-heading span {
  max-width: 250px;
  text-align: right;
}

.section-divider {
  margin: 14px 0;
}

.completion-hint {
  height: auto;
  min-height: 88px;
  margin-top: 12px;
  border-radius: 4px;
}

.create-context {
  gap: 14px;
  padding: 28px 30px;
  overflow-y: auto;
  border-left: 1px solid token.$crm-border-default;
  background: token.$crm-color-subtle;
}

.context-card {
  border-radius: 4px;
}

.duplicate-card,
.duplicate-card--empty,
.result-card,
.rule-card {
  min-height: auto;
  height: auto;
}

@media (max-width: 1500px) {
  .customer-create-page { overflow: hidden; }
  .create-workspace { min-width: 0; }
}
</style>
