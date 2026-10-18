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
import { useAuthStore } from '@/stores/auth'

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
    redirect !== '/login'
  ) {
    return redirect
  }
  return '/'
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

    <div class="login-brand" aria-label="HiTree">HiTree</div>

    <section class="login-hero" aria-labelledby="login-hero-title">
      <p class="hero-kicker">企业运营协同平台</p>
      <h1 id="login-hero-title">客户、订单、生产<br />在一条链路上协同</h1>
      <p class="hero-description">清晰记录每一次跟进、每一笔订单与每一个交付节点。</p>
      <ul class="business-modules" aria-label="平台业务模块">
        <li>客户管理</li>
        <li>询盘与报价</li>
        <li>销售订单</li>
        <li>生产协同</li>
      </ul>
    </section>

    <footer class="login-footer">
      <img :src="shieldIcon" alt="" aria-hidden="true" />
      <span>企业数据仅供授权人员使用</span>
    </footer>

    <section class="login-panel" aria-labelledby="login-title">
      <header class="login-header">
        <div class="secure-label">
          <img :src="statusDot" alt="" aria-hidden="true" />
          <span>安全登录</span>
        </div>
        <h2 id="login-title">欢迎回来</h2>
      </header>

      <ElForm

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


    </section>
  </main>
</template>

<style lang="scss" scoped>
.login-page {
  position: relative;
  width: 100vw;
  min-width: 1200px;
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
  top: 72px;
  left: 120px;
  width: 113px;
  height: 48px;
  overflow: hidden;
  font-family: "Bodoni Moda", "Bodoni MT", Didot, Georgia, serif;
  font-size: 36px;
  font-weight: 600;
  line-height: 44px;
  letter-spacing: -0.8px;
}

.login-hero {
  position: absolute;
  top: 270px;
  left: 120px;
  width: 820px;
  height: 470px;
  overflow: hidden;
}

.hero-kicker {
  margin: 0;
  font-size: 14px;
  font-weight: 500;
  line-height: 22px;
  letter-spacing: 1.6px;
}

.login-hero h1 {
  width: 800px;
  height: 160px;
  margin: 0;
  font-size: 58px;
  font-weight: 700;
  line-height: 76px;
}

.hero-description {
  width: 720px;
  height: 60px;
  margin: 0;
  font-size: 18px;
  font-weight: 400;
  line-height: 30px;
}

.business-modules {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 42px;
  margin: 0;
  padding: 0;
  overflow: hidden;
  list-style: none;
}

.business-modules li {
  height: 36px;
  padding: 0 16px;
  border-radius: 18px;
  background: color-mix(in srgb, var(--erp-color-surface) 82%, transparent);
  font-size: 13px;
  font-weight: 500;
  line-height: 36px;
  white-space: nowrap;
}

.login-footer {
  position: absolute;
  top: 986px;
  left: 120px;
  display: flex;
  align-items: center;
  gap: 9px;
  width: 185px;
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
  left: calc(100vw - 600px);
  width: 440px;
  min-height: 620px;
  color: var(--erp-color-text-inverse);
}

.login-header {
  height: 120px;
  overflow: hidden;
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
  width: 440px;
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

</style>
