<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'

import { createCommunication } from '@/api/crm'
import { createInquiry } from '@/api/workbench'
import { fetchCustomers } from '@/api/customers'
import ResizableDrawerHandle from '@/components/ResizableDrawerHandle.vue'
import { useOptions } from '@/composables/useOptions'
import { useAuthStore } from '@/stores/auth'
import type { CustomerListItem } from '@/types/customer'
import { isUnauthorizedWorkbenchError, workbenchErrorMessage } from '@/utils/workbench'

const props = defineProps<{
  action: 'COMMUNICATION' | 'INQUIRY'
  employeeId: string | null
}>()
const emit = defineEmits<{ saved: [] }>()
const visible = defineModel<boolean>({ required: true })
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const communicationOptions = useOptions('COMMUNICATION_TYPE')
const communicationTypeOptions = communicationOptions.options
const communicationTypeLoading = communicationOptions.loading

const formRef = ref<FormInstance>()
const loadingCustomers = ref(false)
const submitting = ref(false)
const customers = ref<CustomerListItem[]>([])

const form = reactive({
  customerId: '',
  subject: '',
  content: '',
  occurredAt: '',
  requestedDueAt: '',
  communicationType: 'EMAIL',
  direction: 'OUTBOUND' as 'INBOUND' | 'OUTBOUND' | 'INTERNAL',
})

const title = computed(() => props.action === 'COMMUNICATION' ? '记录沟通' : '新建询盘')
const canSubmit = computed(() => props.action === 'COMMUNICATION' || Boolean(props.employeeId))
const rules: FormRules = {
  customerId: [{ required: true, message: '请选择客户', trigger: 'change' }],
  subject: [{ required: true, message: '请输入主题', trigger: 'blur' }, { max: 200, message: '主题最多 200 字', trigger: 'blur' }],
  content: [{ required: true, message: '请输入内容', trigger: 'blur' }, { max: 2000, message: '内容最多 2000 字', trigger: 'blur' }],
  occurredAt: [{ required: true, message: '请选择沟通时间', trigger: 'change' }],
  communicationType: [{ required: true, message: '请选择沟通方式', trigger: 'change' }],
}

function resetForm() {
  form.customerId = ''
  form.subject = ''
  form.content = ''
  form.occurredAt = new Date().toISOString().slice(0, 16)
  form.requestedDueAt = ''
  form.communicationType = 'EMAIL'
  form.direction = 'OUTBOUND'
  formRef.value?.clearValidate()
}

async function loadCustomers() {
  loadingCustomers.value = true
  try {
    const response = await fetchCustomers({ page: 1, page_size: 100, archived: 'false', ordering: 'account_name' })
    customers.value = response.data
  } catch {
    customers.value = []
    ElMessage.error('客户列表加载失败，请稍后重试')
  } finally {
    loadingCustomers.value = false
  }
}

watch(visible, (opened) => {
  if (!opened) return
  resetForm()
  void Promise.all([
    loadCustomers(),
    communicationOptions.load().then((items) => {
      if (!items.some((item) => item.code === form.communicationType)) {
        form.communicationType = items[0]?.code || ''
      }
    }),
  ]).catch(() => ElMessage.error('沟通方式加载失败，请稍后重试'))
})

async function submit() {
  if (!canSubmit.value || submitting.value) return
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (props.action === 'COMMUNICATION') {
      await createCommunication({
        customer_account_id: form.customerId,
        communication_type: form.communicationType,
        direction: form.direction,
        subject: form.subject.trim(),
        content: form.content.trim(),
        occurred_at: new Date(form.occurredAt).toISOString(),
      })
    } else if (props.employeeId) {
      await createInquiry({
        customer_account_id: form.customerId,
        owner_employee_id: props.employeeId,
        subject: form.subject.trim(),
        description: form.content.trim(),
        received_at: new Date().toISOString(),
        requested_due_at: form.requestedDueAt ? new Date(form.requestedDueAt).toISOString() : undefined,
      })
    }
    ElMessage.success(`${title.value}成功`)
    visible.value = false
    emit('saved')
  } catch (error) {
    if (isUnauthorizedWorkbenchError(error)) {
      authStore.clearAuthentication()
      void router.replace({ name: 'login', query: { redirect: route.fullPath } })
    }
    ElMessage.error(workbenchErrorMessage(error, title.value, true))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <ElDrawer v-model="visible" :title="title" size="440px" destroy-on-close append-to-body>
    <ResizableDrawerHandle />
    <ElAlert
      v-if="action === 'INQUIRY' && !employeeId"
      title="当前账号未关联在职员工，无法设置询盘负责人"
      type="warning"
      :closable="false"
      show-icon
      class="quick-drawer__alert"
    />
    <ElForm ref="formRef" :model="form" :rules="rules" label-position="top">
      <ElFormItem label="客户" prop="customerId">
        <ElSelect v-model="form.customerId" filterable :loading="loadingCustomers" placeholder="请选择客户" style="width: 100%">
          <ElOption
            v-for="customer in customers"
            :key="customer.id"
            :label="`${customer.account_code} · ${customer.account_name}`"
            :value="customer.id"
          />
        </ElSelect>
      </ElFormItem>
      <template v-if="action === 'COMMUNICATION'">
        <div class="quick-drawer__row">
          <ElFormItem label="沟通方式" prop="communicationType">
            <ElSelect v-model="form.communicationType" :loading="communicationTypeLoading">
              <ElOption v-for="item in communicationTypeOptions" :key="item.id" :label="item.label" :value="item.code" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="方向">
            <ElSelect v-model="form.direction">
              <ElOption label="我方发起" value="OUTBOUND" />
              <ElOption label="客户发起" value="INBOUND" />
              <ElOption label="内部沟通" value="INTERNAL" />
            </ElSelect>
          </ElFormItem>
        </div>
        <ElFormItem label="沟通时间" prop="occurredAt">
          <ElDatePicker v-model="form.occurredAt" type="datetime" value-format="YYYY-MM-DDTHH:mm" style="width: 100%" />
        </ElFormItem>
      </template>
      <ElFormItem label="主题" prop="subject">
        <ElInput v-model="form.subject" maxlength="200" show-word-limit />
      </ElFormItem>
      <ElFormItem :label="action === 'COMMUNICATION' ? '沟通内容' : '询盘说明'" prop="content">
        <ElInput v-model="form.content" type="textarea" :rows="5" maxlength="2000" show-word-limit />
      </ElFormItem>
      <ElFormItem v-if="action === 'INQUIRY'" label="期望完成时间">
        <ElDatePicker v-model="form.requestedDueAt" type="datetime" value-format="YYYY-MM-DDTHH:mm" style="width: 100%" />
      </ElFormItem>
    </ElForm>
    <template #footer>
      <ElButton @click="visible = false">取消</ElButton>
      <ElButton type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">保存</ElButton>
    </template>
  </ElDrawer>
</template>

<style scoped lang="scss">
.quick-drawer__alert { margin-bottom: 16px; }
.quick-drawer__row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
</style>
