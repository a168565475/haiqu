<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { clearWeComLoginAttempt, isWeComBrowser, resolveMobileRedirect, startWeComLogin } from '@/utils/wecom'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const username = ref('')
const password = ref('')
const busy = ref(false)
const inWeCom = isWeComBrowser()
const message = ref(route.query.reason === 'connection' ? '暂时无法连接系统，请检查网络后重试' : route.query.reason === 'identity' ? '登录身份已变化，请重新登录' : '')
async function submit() {
  if (busy.value) return
  busy.value = true
  message.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    password.value = ''
    clearWeComLoginAttempt()
    await router.replace(resolveMobileRedirect(route.query.redirect))
  } catch (error) { message.value = errorMessage(error, '登录未完成，请重试') }
  finally { busy.value = false }
}
async function retryWeCom() {
  if (busy.value) return
  busy.value = true
  message.value = ''
  try {
    await auth.refresh(true)
    const target = resolveMobileRedirect(route.query.redirect)
    if (auth.user) await router.replace(target)
    else if (auth.accountSwitch?.can_return) message.value = '当前保留了管理员返回入口，请先返回 ERP 恢复管理员身份。'
    else if (!startWeComLogin(target)) message.value = '当前浏览器无法自动登录，请使用 ERP 账号登录。'
  } catch (error) { message.value = errorMessage(error, '暂时无法连接系统，请稍后重试') }
  finally { busy.value = false }
}
</script>

<template>
  <main class="login-page">
    <header class="login-brand">
      <span class="brand-mark" aria-hidden="true"><van-icon name="apps-o" size="24" /></span>
      <span>海趣车间</span>
    </header>
    <section class="login-form" aria-labelledby="login-title">
      <div class="login-heading">
        <h1 id="login-title">登录工作账号</h1>
        <p class="login-description">领料申请 · 生产报工</p>
      </div>
      <van-form class="login-fields" label-align="top" @submit="submit">
        <van-field v-model="username" label="账号" placeholder="请输入 ERP 账号" autocomplete="username" :rules="[{ required: true, message: '请输入账号' }]" :disabled="busy" :border="false" />
        <van-field v-model="password" type="password" label="密码" placeholder="请输入密码" autocomplete="current-password" :rules="[{ required: true, message: '请输入密码' }]" :disabled="busy" :border="false" />
        <div v-if="message" class="error-panel login-error" role="alert">
          <van-icon name="warning-o" aria-hidden="true" />
          <span>{{ message }}</span>
        </div>
        <van-button class="login-submit" type="primary" block native-type="submit" :loading="busy" loading-text="正在登录">登录</van-button>
      </van-form>
      <van-button v-if="inWeCom" class="wecom-retry" plain type="primary" block :disabled="busy" @click="retryWeCom">使用企业微信登录</van-button>
      <p v-if="auth.accountSwitch?.can_return" class="account-note"><a href="/">返回 ERP 恢复管理员身份</a></p>
      <p class="account-note">使用现有 ERP 账号</p>
    </section>
    <p class="login-help"><van-icon name="info-o" aria-hidden="true" /><span>账号或权限有问题，请联系管理员。</span></p>
  </main>
</template>

<style scoped>
.login-page {
  max-width: 480px;
  margin-inline: auto;
  padding: max(28px, env(safe-area-inset-top)) 20px max(32px, env(safe-area-inset-bottom));
  color: var(--mobile-text, #172b4d);
  font-family: inherit;
}
.login-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 28px; font-size: 20px; font-weight: 700; line-height: 1.4; }
.brand-mark { display: grid; place-items: center; flex-shrink: 0; width: 40px; height: 40px; border-radius: 12px; color: var(--mobile-primary, #2563eb); background: var(--mobile-primary-soft, #eaf1ff); }
.login-form { padding: 24px 20px 20px; border: 1px solid var(--mobile-border, #dce4ef); border-radius: 16px; background: var(--mobile-surface, #fff); }
.login-heading { margin-bottom: 28px; }
.login-heading h1 { margin: 0; font-size: 24px; font-weight: 700; line-height: 1.4; }
.login-description { margin: 8px 0 0; color: var(--mobile-muted, #64748b); font-size: 16px; line-height: 1.5; }
.login-fields { display: flex; flex-direction: column; gap: 20px; }
.login-fields :deep(.van-field) { padding: 0; font-family: inherit; }
.login-fields :deep(.van-field__label) { margin: 0 0 8px; color: var(--mobile-text, #172b4d); font-size: 16px; font-weight: 500; line-height: 1.5; }
.login-fields :deep(.van-field__body) { min-height: 48px; padding-inline: 12px; border: 1px solid var(--mobile-border, #dce4ef); border-radius: 10px; background: var(--mobile-surface, #fff); }
.login-fields :deep(.van-field__body:focus-within) { border-color: var(--mobile-primary, #2563eb); outline: 2px solid var(--mobile-primary, #2563eb); outline-offset: 2px; }
.login-fields :deep(.van-field__control) { min-height: 46px; color: var(--mobile-text, #172b4d); font-family: inherit; font-size: 16px; caret-color: var(--mobile-primary, #2563eb); }
.login-fields :deep(.van-field__control:focus-visible) { outline: none; }
.login-fields :deep(.van-field__control::placeholder) { color: var(--mobile-muted, #64748b); }
.login-fields :deep(.van-field--disabled .van-field__body) { background: var(--mobile-canvas, #f3f6fa); }
.login-fields :deep(.van-field__error-message) { margin-top: 6px; font-size: 14px; line-height: 1.5; }
.login-submit { min-height: 48px; margin-top: 4px; border-color: var(--mobile-primary, #2563eb); border-radius: 10px; background: var(--mobile-primary, #2563eb); font-family: inherit; font-size: 16px; font-weight: 600; }
.login-error { display: flex; align-items: flex-start; gap: 8px; padding: 12px; border-radius: 10px; font-size: 14px; line-height: 1.6; }
.login-error .van-icon { flex-shrink: 0; margin-top: 3px; font-size: 18px; }
.account-note { margin: 16px 0 0; color: var(--mobile-muted, #64748b); text-align: center; font-size: 14px; line-height: 1.5; }
.wecom-retry { min-height: 48px; margin-top: 16px; border-radius: 10px; }
.login-help { display: flex; align-items: flex-start; gap: 6px; margin: 18px 4px 0; color: var(--mobile-muted, #64748b); font-size: 14px; line-height: 1.7; }
.login-help .van-icon { flex-shrink: 0; margin-top: 4px; font-size: 16px; }
@media (max-width: 359px) {
  .login-page { padding-inline: 16px; }
  .login-form { padding-inline: 16px; }
}
@media (min-width: 700px) {
  .login-page { padding-top: 48px; }
}
</style>
