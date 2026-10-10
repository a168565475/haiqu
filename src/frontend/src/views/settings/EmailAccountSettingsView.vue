<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { Delete, Edit, Message, Plus, Refresh, Star } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createEmailAccount,
  deleteEmailAccount,
  fetchEmailAccount,
  fetchEmailAccounts,
  sendEmailAccountTest,
  setDefaultEmailAccount,
  updateEmailAccount,
} from '@/api/emailAccounts'
import type { EmailAccount, EmailAccountInput, EmailAccountTestStatus } from '@/types/emailAccount'

type EmailProviderKey = 'qq' | 'netease163' | 'netease126' | 'gmail' | 'aliyun' | 'tencentBusiness' | 'outlook' | 'other'

interface EmailProviderGuide {
  key: EmailProviderKey
  label: string
  supported: boolean
  smtpHost?: string
  smtpPort?: number
  smtpSecurity?: EmailAccountInput['smtp_security']
  authorizationName: string
  steps: string[]
  notice?: string
  helpUrl?: string
  helpLabel?: string
}

const emailProviderGuides: EmailProviderGuide[] = [
  {
    key: 'qq',
    label: 'QQ 邮箱',
    supported: true,
    smtpHost: 'smtp.qq.com',
    smtpPort: 465,
    smtpSecurity: 'SSL',
    authorizationName: '授权码',
    steps: [
      '登录 QQ 邮箱网页版，进入“设置”，找到 POP3/IMAP/SMTP 等服务设置。',
      '开启 SMTP 服务，按页面提示完成身份验证并生成授权码。',
      '复制授权码填入本系统；SMTP 用户名填写完整 QQ 邮箱地址，不要填写 QQ 登录密码。',
    ],
    notice: '如果设置入口名称发生变化，可在 QQ 邮箱设置中搜索“SMTP”或“授权码”。',
    helpUrl: 'https://mail.qq.com/',
    helpLabel: '打开 QQ 邮箱',
  },
  {
    key: 'netease163',
    label: '网易 163',
    supported: true,
    smtpHost: 'smtp.163.com',
    smtpPort: 465,
    smtpSecurity: 'SSL',
    authorizationName: '客户端授权密码',
    steps: [
      '登录 163 邮箱网页版，进入“设置”，找到 POP3/SMTP/IMAP 客户端服务。',
      '开启 SMTP 服务，并按页面提示设置或生成客户端授权密码。',
      '本系统用户名填写完整 163 邮箱地址，授权码栏填写客户端授权密码，不要填写网页登录密码。',
    ],
    helpUrl: 'https://mail.163.com/',
    helpLabel: '打开 163 邮箱',
  },
  {
    key: 'netease126',
    label: '网易 126',
    supported: true,
    smtpHost: 'smtp.126.com',
    smtpPort: 465,
    smtpSecurity: 'SSL',
    authorizationName: '客户端授权密码',
    steps: [
      '登录 126 邮箱网页版，进入“设置”，找到 POP3/SMTP/IMAP 客户端服务。',
      '开启 SMTP 服务，并按页面提示设置或生成客户端授权密码。',
      '本系统用户名填写完整 126 邮箱地址，授权码栏填写客户端授权密码，不要填写网页登录密码。',
    ],
    helpUrl: 'https://mail.126.com/',
    helpLabel: '打开 126 邮箱',
  },
  {
    key: 'gmail',
    label: 'Gmail',
    supported: true,
    smtpHost: 'smtp.gmail.com',
    smtpPort: 465,
    smtpSecurity: 'SSL',
    authorizationName: '应用专用密码',
    steps: [
      '进入 Google 账号的“安全性”，先开启两步验证。',
      '在“应用专用密码”中创建一个用于 Haiqu ERP 的 16 位密码；若看不到该入口，请联系组织管理员确认策略。',
      '本系统用户名填写完整 Gmail 地址，授权码栏填写应用专用密码，不要填写 Google 账号密码。',
    ],
    notice: '修改 Google 账号密码后，原应用专用密码可能失效，需要重新生成并回到本系统更新。',
    helpUrl: 'https://myaccount.google.com/apppasswords',
    helpLabel: '打开 Google 应用专用密码',
  },
  {
    key: 'aliyun',
    label: '阿里企业邮箱',
    supported: true,
    smtpHost: 'smtp.qiye.aliyun.com',
    smtpPort: 465,
    smtpSecurity: 'SSL',
    authorizationName: '三方客户端安全密码',
    steps: [
      '请管理员确认当前账号允许使用第三方客户端和 SMTP 发信。',
      '登录阿里企业邮箱，在账号安全设置中生成“三方客户端安全密码”；若组织未启用该功能，则按管理员要求使用邮箱密码。',
      '本系统用户名填写完整企业邮箱地址，授权码栏优先填写三方客户端安全密码。',
    ],
    notice: '企业自定义 SMTP 域名可能不同；如管理员提供了专用服务器地址，请选择“其他邮箱”并按管理员参数填写。',
    helpUrl: 'https://help.aliyun.com/zh/document_detail/36576.html',
    helpLabel: '查看阿里邮箱官方说明',
  },
  {
    key: 'tencentBusiness',
    label: '腾讯企业邮箱',
    supported: true,
    smtpHost: 'smtp.exmail.qq.com',
    smtpPort: 465,
    smtpSecurity: 'SSL',
    authorizationName: '客户端授权码',
    steps: [
      '请管理员确认企业邮箱账号已允许使用第三方客户端。',
      '登录腾讯企业邮箱，在“设置”中找到客户端服务或安全登录设置，开启 SMTP 并获取客户端授权码。',
      '本系统用户名填写完整企业邮箱地址；开启安全登录后，授权码栏必须填写客户端授权码。',
    ],
    notice: '企业策略可能禁止员工自行开启客户端服务，找不到入口时请联系企业邮箱管理员。',
    helpUrl: 'https://exmail.qq.com/',
    helpLabel: '打开腾讯企业邮箱',
  },
  {
    key: 'outlook',
    label: 'Outlook / Microsoft 365',
    supported: false,
    smtpHost: 'smtp-mail.outlook.com',
    smtpPort: 587,
    smtpSecurity: 'STARTTLS',
    authorizationName: 'OAuth2 现代授权',
    steps: [
      'Outlook.com 官方要求使用 OAuth2（现代授权）。',
      '当前 Haiqu ERP 只支持 SMTP 用户名和授权码，尚未实现 Microsoft OAuth2 登录流程。',
      '请暂时改用其他受支持邮箱，或联系系统管理员评估增加 Microsoft OAuth2。',
    ],
    notice: '不要直接填写 Microsoft 账号密码；即使服务器和端口正确，认证仍可能失败。',
    helpUrl: 'https://support.microsoft.com/en-us/outlook/pop-imap-and-smtp-settings-for-outlook-com',
    helpLabel: '查看 Microsoft 官方说明',
  },
  {
    key: 'other',
    label: '其他邮箱',
    supported: true,
    authorizationName: '授权码或应用密码',
    steps: [
      '登录邮箱网页版，在设置中搜索“SMTP”“客户端服务”“第三方客户端”或“应用密码”。',
      '开启 SMTP，并记录服务商提供的服务器、端口、加密方式和授权码。',
      '若页面没有这些信息，请向企业邮箱管理员索取；不要根据邮箱域名猜测服务器地址。',
    ],
    notice: '本系统只支持 STARTTLS 和 SSL/TLS。若服务商只支持 OAuth2 或专用 API，当前无法接入。',
  },
]

const accounts = ref<EmailAccount[]>([])
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const editorVisible = ref(false)
const testingVisible = ref(false)
const editingId = ref<string | null>(null)
const formRef = ref<FormInstance>()
const testFormRef = ref<FormInstance>()
const selectedForTest = ref<EmailAccount | null>(null)
const selectedProviderKey = ref<EmailProviderKey>('qq')

const form = reactive<EmailAccountInput>({
  display_name: '',
  sender_name: '',
  sender_email: '',
  smtp_host: '',
  smtp_port: 587,
  smtp_username: '',
  smtp_password: '',
  smtp_security: 'STARTTLS',
  is_enabled: true,
})
const testForm = reactive({ recipient: '' })

const editorTitle = computed(() => editingId.value ? '编辑邮件账户' : '新增邮件账户')
const enabledCount = computed(() => accounts.value.filter((item) => item.is_enabled).length)
const selectedProviderGuide = computed(() => (
  emailProviderGuides.find((item) => item.key === selectedProviderKey.value) || emailProviderGuides[emailProviderGuides.length - 1]
))

const formRules: FormRules<EmailAccountInput> = {
  display_name: [{ required: true, message: '请填写配置名称', trigger: 'blur' }],
  sender_email: [{ required: true, type: 'email', message: '请填写有效发件邮箱', trigger: 'blur' }],
  smtp_host: [{ required: true, message: '请填写 SMTP 服务器', trigger: 'blur' }],
  smtp_port: [{ required: true, type: 'number', min: 1, max: 65535, message: '端口范围为 1 至 65535', trigger: 'blur' }],
  smtp_username: [{ required: true, message: '请填写 SMTP 用户名', trigger: 'blur' }],
  smtp_security: [{ required: true, message: '请选择加密方式', trigger: 'change' }],
}
const testRules: FormRules = {
  recipient: [{ required: true, type: 'email', message: '请填写有效测试收件邮箱', trigger: 'blur' }],
}

function apiMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string } } } }).response
  return response?.data?.error?.message || fallback
}

function resetForm() {
  Object.assign(form, {
    display_name: '',
    sender_name: '',
    sender_email: '',
    smtp_host: '',
    smtp_port: 587,
    smtp_username: '',
    smtp_password: '',
    smtp_security: 'STARTTLS',
    is_enabled: true,
  })
  selectedProviderKey.value = 'qq'
  applyProviderPreset('qq')
  formRef.value?.clearValidate()
}

function applyProviderPreset(providerKey: EmailProviderKey) {
  selectedProviderKey.value = providerKey
  const provider = emailProviderGuides.find((item) => item.key === providerKey)
  if (!provider?.supported || !provider.smtpHost || !provider.smtpPort || !provider.smtpSecurity) return
  form.smtp_host = provider.smtpHost
  form.smtp_port = provider.smtpPort
  form.smtp_security = provider.smtpSecurity
}

function inferProviderKey(smtpHost: string): EmailProviderKey {
  return emailProviderGuides.find((item) => item.smtpHost === smtpHost)?.key || 'other'
}

async function loadAccounts() {
  loading.value = true
  errorMessage.value = ''
  try {
    accounts.value = await fetchEmailAccounts()
  } catch (error) {
    errorMessage.value = apiMessage(error, '邮件账户加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  resetForm()
  editorVisible.value = true
}

async function openEdit(account: EmailAccount) {
  saving.value = true
  try {
    const current = await fetchEmailAccount(account.id)
    editingId.value = current.data.id
    Object.assign(form, {
      display_name: current.data.display_name,
      sender_name: current.data.sender_name,
      sender_email: current.data.sender_email,
      smtp_host: current.data.smtp_host,
      smtp_port: current.data.smtp_port,
      smtp_username: current.data.smtp_username,
      smtp_password: '',
      smtp_security: current.data.smtp_security,
      is_enabled: current.data.is_enabled,
    })
    selectedProviderKey.value = inferProviderKey(current.data.smtp_host)
    editorVisible.value = true
  } catch (error) {
    ElMessage.error(apiMessage(error, '读取邮件账户失败，请重试。'))
  } finally {
    saving.value = false
  }
}

async function saveAccount() {
  if (!selectedProviderGuide.value.supported) {
    ElMessage.warning('当前系统尚不支持 Outlook / Microsoft 365 所需的 OAuth2 现代授权。')
    return
  }
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (!editingId.value && !form.smtp_password) {
    ElMessage.warning('新增邮件账户必须填写 SMTP 授权码。')
    return
  }

  saving.value = true
  try {
    if (editingId.value) {
      const current = await fetchEmailAccount(editingId.value)
      const payload: Partial<EmailAccountInput> = { ...form }
      if (!payload.smtp_password) delete payload.smtp_password
      await updateEmailAccount(editingId.value, payload, current.etag)
      ElMessage.success('邮件账户已更新。')
    } else {
      await createEmailAccount({ ...form })
      ElMessage.success('邮件账户已新增。')
    }
    editorVisible.value = false
    await loadAccounts()
  } catch (error) {
    ElMessage.error(apiMessage(error, '邮件账户保存失败，请检查输入后重试。'))
  } finally {
    saving.value = false
  }
}

async function setDefault(account: EmailAccount) {
  if (account.is_default) return
  try {
    await ElMessageBox.confirm(`将“${account.display_name}”设为本账户报价邮件的默认发件邮箱？`, '设为默认', {
      type: 'warning',
      confirmButtonText: '设为默认',
      cancelButtonText: '取消',
    })
    const current = await fetchEmailAccount(account.id)
    await setDefaultEmailAccount(account.id, current.etag)
    ElMessage.success('默认邮件账户已更新。')
    await loadAccounts()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(apiMessage(error, '默认邮件账户设置失败。'))
  }
}

async function toggleEnabled(account: EmailAccount) {
  try {
    const current = await fetchEmailAccount(account.id)
    await updateEmailAccount(account.id, { is_enabled: !account.is_enabled }, current.etag)
    ElMessage.success(account.is_enabled ? '邮件账户已停用。' : '邮件账户已启用。')
    await loadAccounts()
  } catch (error) {
    ElMessage.error(apiMessage(error, '邮件账户状态更新失败。'))
  }
}

async function removeAccount(account: EmailAccount) {
  try {
    await ElMessageBox.confirm(`删除“${account.display_name}”后无法恢复，是否继续？`, '删除邮件账户', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    const current = await fetchEmailAccount(account.id)
    await deleteEmailAccount(account.id, current.etag)
    ElMessage.success('邮件账户已删除。')
    await loadAccounts()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(apiMessage(error, '邮件账户删除失败。'))
  }
}

function openTest(account: EmailAccount) {
  selectedForTest.value = account
  testForm.recipient = ''
  testingVisible.value = true
  testFormRef.value?.clearValidate()
}

function handleAccountAction(command: string, account: EmailAccount) {
  if (command === 'test') {
    openTest(account)
  } else if (command === 'edit') {
    void openEdit(account)
  } else if (command === 'default') {
    void setDefault(account)
  } else if (command === 'toggle') {
    void toggleEnabled(account)
  } else if (command === 'delete') {
    void removeAccount(account)
  }
}

async function sendTest() {
  const valid = await testFormRef.value?.validate().catch(() => false)
  if (!valid || !selectedForTest.value) return
  saving.value = true
  try {
    const current = await fetchEmailAccount(selectedForTest.value.id)
    await sendEmailAccountTest(current.data.id, testForm.recipient, current.etag)
    ElMessage.success('测试邮件已被 SMTP 服务接受，请前往收件箱确认。')
    testingVisible.value = false
    await loadAccounts()
  } catch (error) {
    ElMessage.error(apiMessage(error, '测试邮件发送失败，请检查 SMTP 参数与授权码。'))
    await loadAccounts()
  } finally {
    saving.value = false
  }
}

function testStatusLabel(status: EmailAccountTestStatus): string {
  return { NOT_TESTED: '未测试', SUCCESS: '测试成功', FAILED: '测试失败' }[status]
}

function testStatusType(status: EmailAccountTestStatus): 'info' | 'success' | 'danger' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

onMounted(loadAccounts)
</script>

<template>
  <section class="email-account-settings system-settings-theme" data-testid="email-account-settings-page">
    <nav class="crumb"><span>系统配置</span><span>/</span><b>邮件账户</b></nav>
    <header class="page-heading">
      <div>
        <h1>邮件账户</h1>
        <p>仅管理当前登录账户自己的 SMTP 邮箱；报价发送时会使用启用的默认邮箱。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadAccounts">刷新</el-button>
        <el-button data-testid="create-email-account" type="primary" :icon="Plus" @click="openCreate">新增邮件账户</el-button>
      </div>
    </header>

    <el-alert
      title="安全提示"
      description="请填写邮箱服务商提供的 SMTP 授权码或应用专用密码。密码会加密保存且不会再次显示。"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="metrics">
      <article><span>已配置账户</span><strong>{{ accounts.length }}</strong></article>
      <article><span>已启用账户</span><strong>{{ enabledCount }}</strong></article>
      <article><span>默认发件账户</span><strong>{{ accounts.find((item) => item.is_default)?.display_name || '未设置' }}</strong></article>
    </div>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon>
      <template #default><el-button size="small" @click="loadAccounts">重试</el-button></template>
    </el-alert>

    <el-card shadow="never" class="table-card">
      <el-table v-loading="loading" :data="accounts" empty-text="暂无邮件账户，请先新增一个 SMTP 配置。">
        <el-table-column label="邮件账户" min-width="200">
          <template #default="{ row }"><b>{{ row.display_name }}</b><small>{{ row.sender_name || '未设置发件人名称' }}</small></template>
        </el-table-column>
        <el-table-column prop="sender_email" label="发件邮箱" min-width="210" />
        <el-table-column label="SMTP 服务器" min-width="220">
          <template #default="{ row }"><span>{{ row.smtp_host }}:{{ row.smtp_port }}</span><small>{{ row.smtp_security }}</small></template>
        </el-table-column>
        <el-table-column label="状态" width="170">
          <template #default="{ row }">
            <el-tag class="settings-tag" :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '已启用' : '已停用' }}</el-tag>
            <el-tag v-if="row.is_default" type="warning" class="settings-tag tag-gap">默认</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近测试" min-width="160">
          <template #default="{ row }"><el-tag class="settings-tag" :type="testStatusType(row.last_test_status)">{{ testStatusLabel(row.last_test_status) }}</el-tag><small>{{ row.last_tested_at ? new Date(row.last_tested_at).toLocaleString() : '—' }}</small></template>
        </el-table-column>
        <el-table-column label="操作" width="92" fixed="right">
          <template #default="{ row }">
            <el-dropdown trigger="click" @command="(command: string) => handleAccountAction(command, row)">
              <el-button size="small">更多</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="test" :icon="Message">测试发送</el-dropdown-item>
                  <el-dropdown-item command="edit" :icon="Edit">编辑</el-dropdown-item>
                  <el-dropdown-item command="default" :icon="Star" :disabled="row.is_default || !row.is_enabled">设为默认</el-dropdown-item>
                  <el-dropdown-item command="toggle">{{ row.is_enabled ? '停用' : '启用' }}</el-dropdown-item>
                  <el-dropdown-item command="delete" :icon="Delete" divided class="danger-action">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="editorVisible"
      :title="editorTitle"
      width="min(960px, calc(100vw - 32px))"
      class="email-account-editor-dialog system-settings-dialog"
      align-center
      draggable
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-position="top">
        <section class="provider-guide" data-testid="email-provider-guide">
          <div class="provider-guide-heading">
            <div>
              <h3>第 1 步：选择邮箱服务商</h3>
              <p>系统只会代填公开的服务器参数，不会读取或保存你的邮箱登录密码。</p>
            </div>
          </div>
          <div class="provider-options" aria-label="邮箱服务商">
            <el-button
              v-for="provider in emailProviderGuides"
              :key="provider.key"
              :data-testid="`provider-${provider.key}`"
              :type="selectedProviderKey === provider.key ? 'primary' : 'default'"
              :plain="selectedProviderKey !== provider.key"
              size="small"
              @click="applyProviderPreset(provider.key)"
            >
              {{ provider.label }}
            </el-button>
          </div>

          <el-alert
            v-if="!selectedProviderGuide.supported"
            title="当前系统暂不支持该邮箱"
            :description="selectedProviderGuide.notice"
            type="warning"
            :closable="false"
            show-icon
          />

          <div class="provider-guide-content">
            <div class="provider-steps">
              <h4>第 2 步：获取 {{ selectedProviderGuide.authorizationName }}</h4>
              <ol>
                <li v-for="step in selectedProviderGuide.steps" :key="step">{{ step }}</li>
              </ol>
              <p v-if="selectedProviderGuide.notice && selectedProviderGuide.supported" class="provider-notice">
                {{ selectedProviderGuide.notice }}
              </p>
              <el-link
                v-if="selectedProviderGuide.helpUrl"
                :href="selectedProviderGuide.helpUrl"
                target="_blank"
                rel="noopener noreferrer"
                type="primary"
              >
                {{ selectedProviderGuide.helpLabel }}（新窗口打开）
              </el-link>
            </div>
            <dl v-if="selectedProviderGuide.smtpHost" class="provider-parameters">
              <div><dt>SMTP 服务器</dt><dd>{{ selectedProviderGuide.smtpHost }}</dd></div>
              <div><dt>端口</dt><dd>{{ selectedProviderGuide.smtpPort }}</dd></div>
              <div><dt>加密方式</dt><dd>{{ selectedProviderGuide.smtpSecurity === 'SSL' ? 'SSL/TLS' : 'STARTTLS' }}</dd></div>
              <div><dt>用户名</dt><dd>完整邮箱地址</dd></div>
            </dl>
          </div>
        </section>

        <h3 class="form-section-title">第 3 步：填写并保存</h3>
        <div class="form-grid">
          <el-form-item label="配置名称" prop="display_name">
            <el-input v-model="form.display_name" placeholder="例如：工作邮箱" maxlength="100" />
            <p class="field-help">自行命名，仅用于系统内识别，不需要去邮箱后台获取。</p>
          </el-form-item>
          <el-form-item label="发件人名称" prop="sender_name">
            <el-input v-model="form.sender_name" placeholder="例如：张三 / 海曲外贸" maxlength="150" />
            <p class="field-help">收件人看到的发件人名称，可填写姓名或公司简称。</p>
          </el-form-item>
          <el-form-item label="发件邮箱" prop="sender_email">
            <el-input v-model="form.sender_email" placeholder="name@example.com" />
            <p class="field-help">填写邮箱网页版账号信息中显示的完整邮箱地址。</p>
          </el-form-item>
          <el-form-item label="SMTP 用户名" prop="smtp_username">
            <el-input v-model="form.smtp_username" placeholder="通常为完整邮箱地址" />
            <p class="field-help">通常与发件邮箱相同；企业邮箱以管理员提供的账号为准。</p>
          </el-form-item>
          <el-form-item label="SMTP 服务器" prop="smtp_host">
            <el-input v-model="form.smtp_host" placeholder="例如：smtp.example.com" />
            <p class="field-help">常见服务商已自动填写；其他邮箱请从客户端设置或管理员处获取。</p>
          </el-form-item>
          <el-form-item label="端口" prop="smtp_port">
            <el-input-number v-model="form.smtp_port" :min="1" :max="65535" controls-position="right" class="full-width" />
            <p class="field-help">端口必须和加密方式配套，不能只改其中一项。</p>
          </el-form-item>
          <el-form-item label="加密方式" prop="smtp_security">
            <el-select v-model="form.smtp_security" class="full-width"><el-option label="STARTTLS（通常为 587）" value="STARTTLS" /><el-option label="SSL/TLS（通常为 465）" value="SSL" /></el-select>
            <p class="field-help">按邮箱服务商给出的安全类型选择；本系统不支持不加密连接。</p>
          </el-form-item>
          <el-form-item label="SMTP 授权码" prop="smtp_password">
            <el-input v-model="form.smtp_password" type="password" show-password :placeholder="editingId ? '留空则保留已保存授权码' : `填写${selectedProviderGuide.authorizationName}`" autocomplete="new-password" />
            <p class="field-help">填写上方教程生成的 {{ selectedProviderGuide.authorizationName }}，通常不是邮箱登录密码。</p>
          </el-form-item>
        </div>
        <el-form-item><el-switch v-model="form.is_enabled" active-text="启用此邮件账户" inactive-text="停用此邮件账户" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editorVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!selectedProviderGuide.supported" @click="saveAccount">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="testingVisible" title="测试发送" width="460px" class="system-settings-dialog" draggable destroy-on-close>
      <p class="dialog-hint">将使用“{{ selectedForTest?.display_name }}”向指定地址发送一封固定测试邮件。</p>
      <el-form ref="testFormRef" :model="testForm" :rules="testRules" label-position="top"><el-form-item label="测试收件邮箱" prop="recipient"><el-input v-model="testForm.recipient" placeholder="test@example.com" /></el-form-item></el-form>
      <template #footer><el-button @click="testingVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="sendTest">发送测试邮件</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped lang="scss">
.email-account-settings{min-width:0;color:#1d2129}.crumb{display:flex;gap:8px;align-items:center;margin-bottom:14px;color:#86909c;font-size:13px}.page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:18px}.page-heading h1{margin:0;font-size:28px}.page-heading p{margin:8px 0 0;color:#86909c}.page-actions{display:flex;gap:10px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:16px 0}.metrics article{min-width:0;padding:16px 18px;border:1px solid #e5e6eb;border-radius:8px;background:#fff}.metrics span,.table-card small{display:block;color:#86909c;font-size:12px}.metrics strong{display:block;overflow:hidden;margin-top:8px;font-size:22px;text-overflow:ellipsis;white-space:nowrap}.table-card b{display:block}.tag-gap{margin-left:6px}.provider-guide{margin-bottom:20px;padding:16px;border:1px solid #dbe6f5;border-radius:8px;background:#f7faff}.provider-guide-heading h3,.form-section-title{margin:0;font-size:16px}.provider-guide-heading p{margin:6px 0 0;color:#4e5969;font-size:13px;line-height:1.6}.provider-options{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.provider-options .el-button{margin-left:0}.provider-guide-content{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:18px;margin-top:14px}.provider-steps h4{margin:0 0 8px;font-size:14px}.provider-steps ol{margin:0 0 10px;padding-left:20px;color:#4e5969;font-size:13px;line-height:1.75}.provider-notice{margin:8px 0;color:#d46b08;font-size:12px;line-height:1.6}.provider-parameters{margin:0;padding:12px 14px;border-radius:6px;background:#fff}.provider-parameters div{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid #f2f3f5}.provider-parameters div:last-child{border-bottom:0}.provider-parameters dt{color:#86909c;font-size:12px}.provider-parameters dd{overflow-wrap:anywhere;margin:0;text-align:right;font-size:12px;font-weight:600}.form-section-title{margin-bottom:14px}.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:0 16px}.field-help{margin:5px 0 0;color:#86909c;font-size:12px;line-height:1.5}.full-width{width:100%}.dialog-hint{margin:0 0 16px;color:#4e5969;line-height:1.6}:global(.email-account-editor-dialog){display:flex;flex-direction:column;max-height:calc(100vh - 32px);overflow:hidden}:global(.email-account-editor-dialog .el-dialog__header),:global(.email-account-editor-dialog .el-dialog__footer){flex:0 0 auto}:global(.email-account-editor-dialog .el-dialog__body){flex:1 1 auto;min-height:0;overflow:auto;overscroll-behavior:contain}@media(max-width:760px){.page-heading{flex-direction:column}.page-actions{width:100%}.metrics{grid-template-columns:1fr}.provider-parameters{order:-1}.table-card{overflow-x:auto}:global(.email-account-editor-dialog){max-height:calc(100vh - 16px)}}
</style>
