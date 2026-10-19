<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { getAuthErrorMessage } from '@/api/auth'
import businessFlowContours from '@/assets/login/business-flow-contours.svg'
import goldBloom from '@/assets/login/gold-bloom.svg'
import lockIcon from '@/assets/login/lock.svg'
import previewOpenIcon from '@/assets/login/preview-open.svg'
import shieldIcon from '@/assets/login/shield.svg'
import statusDot from '@/assets/login/status-dot.svg'
import terracottaHalo from '@/assets/login/terracotta-halo.svg'
import userIcon from '@/assets/login/user.svg'
import headerLogo from '@/assets/navigation/hitree-header-logo.png'
import LoginFlowIllustration from '@/components/auth/LoginFlowIllustration.vue'
import WeComQrLogin from '@/components/auth/WeComQrLogin.vue'
import { useAuthStore } from '@/stores/auth'
import type { AuthResponse } from '@/types/auth'

interface LoginForm {
  username: string
  password: string
}

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const passwordVisible = ref(false)
const loginMode = ref<'password' | 'qr'>('password')
const switchingMode = ref(false)
const qrLoginRef = ref<InstanceType<typeof WeComQrLogin>>()
const form = reactive<LoginForm>({
  username: '',
  password: '',
})

const rules: FormRules<LoginForm> = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { max: 150, message: '用户名不能超过 150 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { max: 128, message: '密码不能超过 128 个字符', trigger: 'blur' },
  ],
}

function resolveSafeRedirect(): string {
  const redirect = route.query.redirect
  if (
    typeof redirect === 'string' &&
    redirect.startsWith('/') &&
    !redirect.startsWith('//') &&
    !/[\\\u0000-\u001f\u007f]/.test(redirect) &&
    !/^\/(?:login|auth|api|admin)(?:[/?#]|$)/.test(redirect)
  ) {
    return redirect
  }
  return '/'
}

async function toggleLoginMode() {
  if (loading.value || switchingMode.value) return
  if (loginMode.value === 'password') {
    loginMode.value = 'qr'
    return
  }
  switchingMode.value = true
  try {
    if (await qrLoginRef.value?.cancel()) loginMode.value = 'password'
  } finally {
    switchingMode.value = false
  }
}

async function continueExistingSession(response: AuthResponse) {
  authStore.applyAuthResponse(response)
  await router.replace(resolveSafeRedirect())
}

async function submitLogin() {
  if (loading.value || !formRef.value) {
    return
  }

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }

  loading.value = true
  try {
    await authStore.login({ username: form.username.trim(), password: form.password })
    ElMessage.success('登录成功')
    await router.replace(resolveSafeRedirect())
  } catch (error) {
    ElMessage.error(getAuthErrorMessage(error))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <div class="ambient ambient-gold" aria-hidden="true">
      <img :src="goldBloom" alt="" />
    </div>
    <div class="ambient ambient-terracotta" aria-hidden="true">
      <img :src="terracottaHalo" alt="" />
    </div>
    <div class="form-contrast-scrim" aria-hidden="true"></div>
    <img
      class="business-flow-contours"
      :src="businessFlowContours"
      alt=""
      aria-hidden="true"
    />

    <div class="login-brand" aria-label="HiTree" :style="{ '--login-brand-image': `url(${headerLogo})` }">
      <span class="login-brand-symbol" aria-hidden="true"></span>
      <span class="login-brand-word">HiTree</span>
    </div>

    <section class="login-hero" aria-label="企业运营协同平台">
      <LoginFlowIllustration />
      <p class="hero-caption">客户、订单、生产，在一条链路上协同</p>
    </section>

    <footer class="login-footer">
      <img :src="shieldIcon" alt="" aria-hidden="true" />
      <span>企业数据仅供授权人员使用</span>
    </footer>

    <section class="login-panel" :class="{ 'login-panel--qr': loginMode === 'qr' }" aria-labelledby="login-title">
      <span class="mode-hint" aria-hidden="true">{{ loginMode === 'password' ? '企业微信扫码' : '账号密码登录' }}</span>
      <button
        type="button"
        class="mode-switch"
        :aria-label="loginMode === 'password' ? '切换企业微信扫码登录' : '切换账号密码登录'"
        :disabled="loading || switchingMode"
        @click="toggleLoginMode"
      >
        <svg v-if="loginMode === 'password'" viewBox="0 0 32 32" fill="none" aria-hidden="true">
          <path d="M3 3h10v10H3zM19 3h10v10H19zM3 19h10v10H3z" stroke="currentColor" stroke-width="2.5" />
          <path d="M7 7h2v2H7zM23 7h2v2h-2zM7 23h2v2H7zM19 18h4v4h-4zM26 18h3v3h-3zM25 25h4v4h-4zM18 25h3v4h-3z" fill="currentColor" />
        </svg>
        <svg v-else viewBox="0 0 32 32" fill="none" aria-hidden="true">
          <rect x="3" y="5" width="26" height="18" rx="2" stroke="currentColor" stroke-width="2.4" />
          <path d="M11 28h10M16 23v5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
        </svg>
      </button>
      <header class="login-header">
        <div class="secure-label">
          <img :src="statusDot" alt="" aria-hidden="true" />
          <span>安全登录</span>
        </div>
        <h2 id="login-title">{{ loginMode === 'password' ? '欢迎回来' : '企业微信扫码登录' }}</h2>
      </header>

      <ElForm
        v-show="loginMode === 'password'"
        ref="formRef"
        :model="form"
        :rules="rules"
        class="login-form"
        @keyup.enter="submitLogin"
      >
        <div class="login-field">
          <label for="login-username">账号</label>
          <ElFormItem prop="username">
            <ElInput
              id="login-username"
              v-model="form.username"
              autocomplete="username"
              aria-label="账号"
              maxlength="150"
              placeholder="请输入账号"
              :disabled="loading"
            >
              <template #prefix>
                <img class="field-icon" :src="userIcon" alt="" aria-hidden="true" />
              </template>
            </ElInput>
          </ElFormItem>
        </div>

        <div class="login-field">
          <label for="login-password">密码</label>
          <ElFormItem prop="password">
            <ElInput
              id="login-password"
              v-model="form.password"
              :type="passwordVisible ? 'text' : 'password'"
              autocomplete="current-password"
              aria-label="密码"
              maxlength="128"
              placeholder="请输入密码"
              :disabled="loading"
            >
              <template #prefix>
                <img class="field-icon" :src="lockIcon" alt="" aria-hidden="true" />
              </template>
              <template #suffix>
                <button
                  type="button"
                  class="password-toggle"
                  :aria-label="passwordVisible ? '隐藏密码' : '显示密码'"
                  :aria-pressed="passwordVisible"
                  :disabled="loading"
                  @click="passwordVisible = !passwordVisible"
                >
                  <img :src="previewOpenIcon" alt="" aria-hidden="true" />
                </button>
              </template>
            </ElInput>
          </ElFormItem>
        </div>

        <div class="login-actions">
          <ElButton
            type="primary"
            class="login-button"
            :loading="loading"
            @click="submitLogin"
          >
            登录
          </ElButton>
          <p>如无法登录，请联系系统管理员。</p>
        </div>
      </ElForm>
      <WeComQrLogin
        v-if="loginMode === 'qr'"
        ref="qrLoginRef"
        :next-path="resolveSafeRedirect()"
        @authenticated="continueExistingSession"
      />
    </section>
  </main>
</template>

<style lang="scss" scoped>
.login-page {
  position: relative;
  width: 100%;
  min-height: 100vh;
  overflow: hidden;
  color: var(--erp-color-text-primary);
  background: var(--erp-login-background);
}

.ambient {
  position: absolute;
  pointer-events: none;
}

.login-page img {
  filter: var(--erp-login-art-filter);
}

.ambient img {
  position: absolute;
  display: block;
  width: 100%;
  height: 100%;
}

.ambient-gold {
  top: -480px;
  left: -360px;
  width: 1080px;
  height: 1080px;
}

.ambient-gold img {
  inset: -6.48%;
  width: 112.96%;
  height: 112.96%;
}

.ambient-terracotta {
  top: 520px;
  left: 520px;
  width: 980px;
  height: 980px;
}

.ambient-terracotta img {
  inset: -9.18%;
  width: 118.36%;
  height: 118.36%;
}

.form-contrast-scrim {
  position: absolute;
  inset: 0 0 0 auto;
  width: 900px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--erp-overlay-scrim-color) 18%, transparent) 38%, color-mix(in srgb, var(--erp-overlay-scrim-color) 48%, transparent));
  pointer-events: none;
}

.business-flow-contours {
  position: absolute;
  top: 660px;
  left: 0;
  width: 1040px;
  height: 420px;
  pointer-events: none;
}

.login-brand {
  position: absolute;
  top: 64px;
  left: 120px;
  display: flex;
  align-items: center;
  gap: 12px;
  height: 60px;
  color: var(--erp-logo-wordmark-color);
}

.login-brand-symbol {
  position: relative;
  width: 52px;
  height: 58px;
  overflow: hidden;
  flex: none;
}
.login-brand-symbol::before {
  content: '';
  position: absolute;
  left: -17px;
  top: -9px;
  width: 224px;
  height: 75px;
  background: var(--login-brand-image) center / contain no-repeat;
  clip-path: inset(0 69% 0 0);
  filter: var(--erp-logo-filter);
}
.login-brand-word {
  font-family: Arial, 'Microsoft YaHei', sans-serif;
  font-size: 35px;
  font-weight: 700;
  letter-spacing: -1.2px;
}
.login-hero {
  position: absolute;
  top: 134px;
  left: 72px;
  width: 980px;
  text-align: center;
}
.hero-caption {
  margin: 0;
  font-size: 16px;
  font-weight: 500;
  line-height: 24px;
  letter-spacing: 1px;
  color: var(--erp-color-text-secondary);
}

.login-footer {
  position: absolute;
  bottom: 62px;
  left: 120px;
  display: flex;
  align-items: center;
  gap: 9px;
  height: 32px;
  overflow: hidden;
  font-size: 13px;
  line-height: 20px;
}

.login-footer img {
  width: 20px;
  height: 20px;
}

.login-panel {
  position: absolute;
  top: 214px;
  right: 160px;
  width: 440px;
  min-height: 620px;
  color: var(--erp-color-text-inverse);
}

.login-header {
  height: 120px;
}

.secure-label {
  display: flex;
  align-items: center;
  gap: 9px;
  height: 24px;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
  letter-spacing: 1.2px;
}

.secure-label img {
  width: 8px;
  height: 8px;
}

.login-header h2 {
  margin: 0;
  font-size: 42px;
  font-weight: 700;
  line-height: 68px;
}

.login-form {
  width: 100%;
}

.login-field {
  height: 93px;
}

.login-field:first-child {
  margin-bottom: 18px;
}

.login-field label {
  display: block;
  height: 31px;
  font-size: 14px;
  font-weight: 500;
  line-height: 22px;
}

.login-form :deep(.el-form-item) {
  margin: 0;
}

.login-form :deep(.el-input__wrapper) {
  height: 60px;
  padding: 0 18px;
  border-radius: 14px;
  background: color-mix(in srgb, var(--erp-color-text-inverse) 14%, transparent);
  box-shadow: none;
}

.login-form :deep(.el-input__wrapper:hover) {
  background: color-mix(in srgb, var(--erp-color-text-inverse) 18%, transparent);
  box-shadow: none;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  background: color-mix(in srgb, var(--erp-color-text-inverse) 20%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--erp-color-text-inverse) 42%, transparent) inset;
}

.login-form :deep(.el-input__prefix-inner) {
  margin-right: 12px;
}

.field-icon {
  display: block;
  width: 22px;
  height: 22px;
}

.login-form :deep(.el-input__inner) {
  height: 60px;
  color: var(--erp-color-text-inverse);
  font-size: 16px;
  line-height: 24px;
}

.login-form :deep(.el-input__inner::placeholder) {
  color: color-mix(in srgb, var(--erp-color-text-inverse) 72%, transparent);
}

.login-form :deep(.el-input__suffix-inner) {
  margin-left: 12px;
}

.password-toggle {
  display: grid;
  width: 24px;
  height: 32px;
  padding: 0;
  border: 0;
  background: transparent;
  place-items: center;
  cursor: pointer;
}

.password-toggle:focus-visible {
  border-radius: 4px;
  outline: 2px solid color-mix(in srgb, var(--erp-color-text-inverse) 80%, transparent);
  outline-offset: 2px;
}

.password-toggle img {
  display: block;
  width: 20px;
  height: 20px;
}

.login-form :deep(.el-form-item__error) {
  top: 60px;
  color: var(--erp-color-surface);
  font-size: 12px;
  line-height: 18px;
}

.login-actions {
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 18px;
  height: 128px;
  padding: 28px 0 6px;
}

.login-button {
  width: 100%;
  height: 56px;
  margin: 0;
  border: 0;
  border-radius: 14px;
  color: var(--erp-color-text-primary);
  background: var(--erp-color-surface);
  box-shadow: none;
  font-size: 16px;
  font-weight: 500;
  letter-spacing: 1.6px;
}

.login-button:hover,
.login-button:focus {
  border: 0;
  color: var(--erp-color-text-primary);
  background: var(--erp-color-hover);
}

.login-actions p {
  margin: 0;
  color: color-mix(in srgb, var(--erp-color-text-inverse) 72%, transparent);
  font-size: 13px;
  line-height: 20px;
}

.login-panel--qr .login-header h2 { font-size: 32px; letter-spacing: -.6px; }
.mode-switch {
  position: absolute;
  right: 0;
  top: -8px;
  width: 48px;
  height: 48px;
  padding: 6px 4px 12px 12px;
  border: 0;
  border-radius: 0 8px 0 0;
  color: var(--erp-color-text-inverse);
  background: linear-gradient(225deg, rgb(255 255 255 / 16%) 0 58%, transparent 59%);
  cursor: pointer;
}
.mode-switch svg { display: block; width: 30px; height: 30px; }
.mode-switch:hover { background: linear-gradient(225deg, rgb(255 255 255 / 26%) 0 58%, transparent 59%); }
.mode-switch:focus-visible { outline: 2px solid currentColor; outline-offset: 4px; }
.mode-switch:disabled { opacity: .5; cursor: wait; }
.mode-hint {
  position: absolute;
  right: 60px;
  top: -2px;
  padding: 5px 9px;
  border: 1px solid rgb(255 255 255 / 30%);
  border-radius: 5px;
  color: rgb(255 255 255 / 88%);
  font-size: 12px;
  line-height: 18px;
  pointer-events: none;
}
.mode-hint::after {
  content: '';
  position: absolute;
  top: 9px;
  right: -4px;
  width: 6px;
  height: 6px;
  border-top: 1px solid rgb(255 255 255 / 30%);
  border-right: 1px solid rgb(255 255 255 / 30%);
  transform: rotate(45deg);
}
@media (max-width: 1600px) {
  .login-brand, .login-footer { left: 80px; }
  .login-hero { left: 28px; top: 146px; width: 800px; }
  .hero-caption { font-size: 15px; }
  .login-panel { right: 80px; top: 204px; }
  .login-footer { bottom: 50px; }
}
@media (max-width: 1100px) {
  .login-brand, .login-footer { left: 48px; }
  .login-hero { left: 20px; top: 196px; width: calc(100% - 480px); }
  .hero-caption { font-size: 12px; letter-spacing: 0; }
  .login-panel { right: 48px; width: 380px; }
}
@media (max-width: 760px) {
  .login-page { min-height: max(844px, 100dvh); }
  .login-brand { left: 26px; top: 25px; height: 44px; gap: 8px; }
  .login-brand-symbol { width: 38px; height: 43px; }
  .login-brand-symbol::before { left: -12px; top: -7px; width: 166px; height: 55px; }
  .login-brand-word { font-size: 26px; }
  .login-hero { left: 50%; top: 68px; transform: translateX(-50%); width: 350px; max-width: 96%; height: 170px; overflow: hidden; }
  .login-hero :deep(.flow-illustration) { width: 266.667px; margin: 0 auto; transform: translateY(-20px); }
  .hero-caption { display: none; }
  .login-panel { left: 50%; right: auto; top: 241px; transform: translateX(-50%); width: calc(100% - 48px); max-width: 440px; min-height: 530px; }
  .login-header { height: 100px; }
  .login-header h2 { font-size: 32px; line-height: 56px; }
  .login-panel--qr .login-header h2 { font-size: 26px; line-height: 56px; }
  .mode-hint { right: 52px; font-size: 11px; padding: 4px 7px; }
  .mode-switch { width: 44px; height: 44px; top: -6px; }
  .mode-switch svg { width: 27px; height: 27px; }
  .login-footer { left: 0; bottom: 24px; justify-content: center; width: 100%; color: #dce9f3; font-size: 11px; }
  .login-footer img { width: 16px; height: 16px; filter: brightness(0) invert(1); opacity: .85; }
  .business-flow-contours { left: -140px; top: 640px; width: 720px; height: auto; opacity: .5; }
}

</style>
