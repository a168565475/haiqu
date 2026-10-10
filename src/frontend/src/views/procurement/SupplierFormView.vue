<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ArrowLeft, Check, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { createSupplier, fetchSupplier, fetchSupplierOptions, updateSupplier } from '@/api/suppliers'
import { useAuthStore } from '@/stores/auth'
import type { Supplier, SupplierInput, SupplierOptions } from '@/types/supplier'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const supplierId = computed(() => typeof route.params.supplierId === 'string' ? route.params.supplierId : '')
const isEditing = computed(() => Boolean(supplierId.value))
const isSuperuser = computed(() => authStore.user?.is_superuser === true)
const can = (permission: string) => isSuperuser.value || authStore.hasPermission(permission)
const canUsePage = computed(() => isEditing.value
  ? can('procurement.change_supplier')
  : can('procurement.add_supplier'))

const formRef = ref<FormInstance>()
const loading = ref(true)
const saving = ref(false)
const loadError = ref('')
const currentEtag = ref('')
const supplier = ref<Supplier | null>(null)
const options = ref<SupplierOptions>({
  supplier_types: [],
  supplier_categories: [],
  payment_cycles: [],
  next_supplier_number: 'GYS00266',
})

function emptyForm(): SupplierInput {
  return {
    supplier_type: 'MATERIAL',
    supplier_categories: [],
    supplier_name: '',
    payment_cycle: '',
    remark: '',
    phone: '',
    is_disabled: false,
  }
}

const form = reactive<SupplierInput>(emptyForm())
const title = computed(() => isEditing.value ? '编辑供应商' : '新建供应商')
const displayedNumber = computed(() => supplier.value?.supplier_number || options.value.next_supplier_number)

const rules: FormRules<SupplierInput> = {
  supplier_type: [{ required: true, message: '请选择供应商类型', trigger: 'change' }],
  supplier_categories: [{ type: 'array', required: true, min: 1, message: '请至少选择一个供应商类别', trigger: 'change' }],
  supplier_name: [
    { required: true, message: '请输入供应商名称', trigger: 'blur' },
    { max: 255, message: '供应商名称不能超过 255 个字符', trigger: 'blur' },
  ],
  phone: [
    { max: 100, message: '联系电话不能超过 100 个字符', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        const normalized = value.trim()
        if (!normalized || (/^(?=.*\d)[0-9+\-()（）\s#.,，、/:：转分机extEXT]+$/.test(normalized) && normalized.length >= 3)) callback()
        else callback(new Error('联系电话格式不正确'))
      },
      trigger: 'blur',
    },
  ],
  remark: [{ max: 2000, message: '备注不能超过 2000 个字符', trigger: 'blur' }],
}

function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as {
    response?: {
      status?: number
      data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string }
    }
  })?.response
  const firstFieldError = response?.data?.error?.field_errors
    ? Object.values(response.data.error.field_errors).flat()[0]
    : ''
  if (response?.status === 412) return '该供应商已被其他人修改，请返回列表后重新进入。'
  if (response?.status === 428) return '缺少并发校验信息，请刷新页面后重试。'
  return firstFieldError || response?.data?.error?.message || response?.data?.detail || fallback
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date).replaceAll('/', '-')
}

async function load(): Promise<void> {
  if (!canUsePage.value) {
    loading.value = false
    return
  }
  loading.value = true
  loadError.value = ''
  try {
    if (isEditing.value) {
      const [nextOptions, response] = await Promise.all([
        fetchSupplierOptions(),
        fetchSupplier(supplierId.value),
      ])
      options.value = nextOptions
      supplier.value = response.data
      currentEtag.value = response.etag
      Object.assign(form, {
        supplier_type: response.data.supplier_type,
        supplier_categories: [...response.data.supplier_categories],
        supplier_name: response.data.supplier_name,
        payment_cycle: response.data.payment_cycle,
        remark: response.data.remark,
        phone: response.data.phone,
        is_disabled: response.data.is_disabled,
      })
    } else {
      options.value = await fetchSupplierOptions()
      Object.assign(form, emptyForm())
    }
    await nextTick()
    formRef.value?.clearValidate()
  } catch (error) {
    loadError.value = apiErrorMessage(error, '供应商资料加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!formRef.value || saving.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  const payload: SupplierInput = {
    supplier_type: form.supplier_type,
    supplier_categories: [...form.supplier_categories],
    supplier_name: form.supplier_name.trim(),
    payment_cycle: form.payment_cycle,
    remark: form.remark.trim(),
    phone: form.phone.trim(),
    is_disabled: form.is_disabled,
  }

  saving.value = true
  try {
    if (isEditing.value) {
      await updateSupplier(supplierId.value, payload, currentEtag.value)
      ElMessage.success('供应商资料已更新')
    } else {
      await createSupplier(payload)
      ElMessage.success('供应商已创建')
    }
    await router.push({ name: 'suppliers' })
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '供应商保存失败，请稍后重试。'))
  } finally {
    saving.value = false
  }
}

function back(): void {
  void router.push({ name: 'suppliers' })
}

onMounted(load)
</script>

<template>
  <section class="supplier-form-page" data-testid="supplier-form-page">
    <div v-if="!canUsePage" class="state-page">
      <h1>无权{{ isEditing ? '编辑' : '新建' }}供应商</h1>
      <p>请联系管理员开通对应权限后重试。</p>
      <ElButton @click="back">返回供应商列表</ElButton>
    </div>

    <template v-else>
      <header class="form-heading">
        <div>
          <ElButton :icon="ArrowLeft" circle aria-label="返回供应商列表" @click="back" />
          <div>
            <div class="breadcrumb">采购管理 <span>/</span> 供应商 <span>/</span> {{ title }}</div>
            <h1>{{ title }}</h1>
          </div>
        </div>
        <div class="form-heading__actions">
          <ElButton :disabled="saving" @click="back">取消</ElButton>
          <ElButton type="primary" :icon="Check" :loading="saving" :disabled="loading || Boolean(loadError)" @click="save">
            {{ isEditing ? '保存修改' : '创建供应商' }}
          </ElButton>
        </div>
      </header>

      <ElAlert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon class="load-error">
        <template #default><ElButton link @click="load">重新加载</ElButton></template>
      </ElAlert>

      <div v-loading="loading" class="form-layout">
        <article class="form-card">
          <div class="card-title">
            <div><h2>基本信息</h2><p>带 <i>*</i> 的字段为必填项</p></div>
          </div>

          <ElForm ref="formRef" :model="form" :rules="rules" label-position="top" class="supplier-form">
            <div class="form-grid">
              <ElFormItem label="供应商编号">
                <ElInput :model-value="displayedNumber" disabled />
                <p class="field-help">系统根据现有资料自动生成，保存后不可修改</p>
              </ElFormItem>

              <ElFormItem label="供应商类型" prop="supplier_type" required>
                <ElSelect v-model="form.supplier_type" placeholder="请选择供应商类型">
                  <ElOption v-for="item in options.supplier_types" :key="item.value" :label="item.label" :value="item.value" />
                </ElSelect>
              </ElFormItem>

              <ElFormItem label="供应商名称" prop="supplier_name" required>
                <ElInput v-model="form.supplier_name" maxlength="255" placeholder="请输入供应商名称" />
              </ElFormItem>

              <ElFormItem label="付款周期" prop="payment_cycle">
                <ElSelect v-model="form.payment_cycle" clearable placeholder="请选择付款周期">
                  <ElOption v-for="item in options.payment_cycles" :key="item.value" :label="item.label" :value="item.value" />
                </ElSelect>
              </ElFormItem>

              <ElFormItem class="category-field" label="供应商类别" prop="supplier_categories" required>
                <ElCheckboxGroup v-model="form.supplier_categories" class="category-options">
                  <ElCheckbox v-for="item in options.supplier_categories" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </ElCheckbox>
                </ElCheckboxGroup>
                <p class="field-help">可多选，至少选择一个类别</p>
              </ElFormItem>

              <ElFormItem label="联系电话" prop="phone">
                <ElInput v-model="form.phone" maxlength="100" placeholder="请输入联系电话" />
              </ElFormItem>

              <ElFormItem label="是否禁用" prop="is_disabled">
                <ElRadioGroup v-model="form.is_disabled">
                  <ElRadio :value="false">否</ElRadio>
                  <ElRadio :value="true">是</ElRadio>
                </ElRadioGroup>
              </ElFormItem>

              <ElFormItem class="remark-field" label="备注" prop="remark">
                <ElInput
                  v-model="form.remark"
                  type="textarea"
                  :rows="5"
                  maxlength="2000"
                  show-word-limit
                  resize="none"
                  placeholder="请输入备注信息"
                />
              </ElFormItem>
            </div>
          </ElForm>
        </article>

        <aside class="side-column">
          <article class="info-card">
            <div class="info-card__title"><ElIcon><InfoFilled /></ElIcon><h2>编号规则</h2></div>
            <dl class="rule-list">
              <div><dt>编号格式</dt><dd>GYS + 5 位流水号</dd></div>
              <div><dt>当前编号</dt><dd>{{ displayedNumber }}</dd></div>
              <div><dt>生成方式</dt><dd>创建时由系统自动生成</dd></div>
            </dl>
          </article>

          <article v-if="isEditing && supplier" class="info-card">
            <h2>资料记录</h2>
            <dl class="record-list">
              <div><dt>提交人</dt><dd>{{ supplier.submitted_by_name || '—' }}</dd></div>
              <div><dt>提交时间</dt><dd>{{ formatDateTime(supplier.submitted_at) }}</dd></div>
              <div><dt>最后更新</dt><dd>{{ formatDateTime(supplier.updated_at) }}</dd></div>
              <div><dt>更新人</dt><dd>{{ supplier.updated_by_name || '—' }}</dd></div>
            </dl>
          </article>

          <article v-if="isEditing && supplier?.duplicate_suppliers?.length" class="info-card duplicate-card">
            <h2>同名供应商</h2>
            <p>当前名称还对应以下供应商编号，请确认是否为独立主体。</p>
            <button
              v-for="item in supplier.duplicate_suppliers"
              :key="item.id"
              type="button"
              @click="router.push({ name: 'supplier-edit', params: { supplierId: item.id } })"
            >
              <strong>{{ item.supplier_number }}</strong>
              <span :class="{ 'is-disabled': item.is_disabled }">{{ item.status_display }}</span>
            </button>
          </article>
        </aside>
      </div>
    </template>
  </section>
</template>

<style lang="scss" scoped>
.supplier-form-page { min-width: 1280px; min-height: calc(100vh - 56px); padding: 24px 32px 40px; color: #202124; background: var(--erp-page-background); --el-color-primary: #18181b; }
.form-heading { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.form-heading > div:first-child { display: flex; align-items: center; gap: 12px; }
.breadcrumb { margin-bottom: 5px; color: #8a8f98; font-size: 12px; }
.breadcrumb span { padding: 0 5px; color: #b8bcc3; }
.form-heading h1 { margin: 0; font-size: 24px; line-height: 30px; }
.form-heading__actions { display: flex; gap: 8px; }
.form-heading__actions :deep(.el-button + .el-button) { margin-left: 0; }
.load-error { margin-bottom: 16px; }
.form-layout { display: grid; grid-template-columns: minmax(0, 1080px) 516px; gap: 20px; min-height: 650px; }
.form-card, .info-card { border: 1px solid #e4e7eb; border-radius: 8px; background: #fff; box-shadow: 0 1px 2px rgb(15 23 42 / 3%); }
.form-card { min-height: 650px; padding: 0 28px 28px; }
.card-title { display: flex; min-height: 70px; align-items: center; border-bottom: 1px solid #eceef1; }
.card-title h2, .info-card h2 { margin: 0; font-size: 16px; }
.card-title p { margin: 5px 0 0; color: #8a8f98; font-size: 12px; }
.card-title i { color: #e24a4a; font-style: normal; }
.supplier-form { padding-top: 22px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 30px; row-gap: 2px; }
.supplier-form :deep(.el-form-item) { margin-bottom: 20px; }
.supplier-form :deep(.el-form-item__label) { height: 23px; padding: 0; color: #3f434a; font-size: 13px; line-height: 20px; }
.supplier-form :deep(.el-input), .supplier-form :deep(.el-select) { width: 100%; }
.field-help { width: 100%; margin: 5px 0 0; color: #969ba4; font-size: 11px; line-height: 16px; }
.category-field, .remark-field { grid-column: 1 / -1; }
.category-options { display: grid; width: 100%; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; padding: 13px 16px; border: 1px solid #dcdfe6; border-radius: 4px; background: #fafbfc; }
.category-options :deep(.el-checkbox) { margin-right: 0; }
.remark-field :deep(.el-textarea__inner) { min-height: 116px !important; }
.side-column { display: flex; flex-direction: column; gap: 16px; }
.info-card { padding: 20px; }
.info-card__title { display: flex; align-items: center; gap: 8px; padding-bottom: 14px; border-bottom: 1px solid #eceef1; }
.info-card__title .el-icon { color: #62666d; }
.rule-list, .record-list { margin: 0; }
.rule-list > div, .record-list > div { display: grid; grid-template-columns: 106px minmax(0, 1fr); gap: 14px; padding: 13px 0; border-bottom: 1px solid #f0f1f3; font-size: 13px; }
.rule-list > div:last-child, .record-list > div:last-child { border-bottom: 0; }
.rule-list dt, .record-list dt { color: #8a8f98; }
.rule-list dd, .record-list dd { margin: 0; color: #30343a; text-align: right; }
.info-card > h2 { margin-bottom: 12px; }
.duplicate-card > p { margin: 0 0 12px; color: #7a7f87; font-size: 12px; line-height: 20px; }
.duplicate-card button { width: 100%; display: flex; align-items: center; justify-content: space-between; margin-top: 8px; padding: 10px 12px; border: 1px solid #e4e7eb; border-radius: 5px; color: #30343a; background: #fafbfc; cursor: pointer; }
.duplicate-card button:hover { border-color: #aeb3bb; }
.duplicate-card button span { color: #3d8d45; font-size: 12px; }
.duplicate-card button span.is-disabled { color: #d9534f; }
.state-page { display: grid; min-height: 520px; place-content: center; gap: 10px; text-align: center; }
.state-page h1, .state-page p { margin: 0; }
.state-page p { color: #7a7f87; }
.state-page .el-button { margin-top: 6px; }
</style>
