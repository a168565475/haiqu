<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { getAuthErrorMessage } from '@/api/auth'
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
    <section class="login-card" aria-labelledby="login-title">
      <div class="card-content">
        <header class="login-header">
          <h1 id="login-title">欢迎回来</h1>
          <p>登录企业ERP管理平台</p>
        </header>

        <ElForm
          ref="formRef"
          :model="form"
          :rules="rules"
          size="large"
          class="login-form"
          @keyup.enter="submitLogin"
        >
          <ElFormItem prop="username">
            <ElInput
              v-model="form.username"
              autocomplete="username"
              aria-label="账号"
              maxlength="150"
              placeholder="账号"
              clearable
              :disabled="loading"
            >
              <template #prefix>
                <ElIcon><User /></ElIcon>
              </template>
            </ElInput>
          </ElFormItem>

          <ElFormItem prop="password">
            <ElInput
              v-model="form.password"
              type="password"
              autocomplete="current-password"
              aria-label="密码"
              maxlength="128"
              placeholder="密码"
              show-password
              :disabled="loading"
            >
              <template #prefix>
                <ElIcon><Lock /></ElIcon>
              </template>
            </ElInput>
          </ElFormItem>

          <ElButton
            type="primary"
            size="large"
            class="login-button"
            :loading="loading"
            @click="submitLogin"
          >
            登录
          </ElButton>
        </ElForm>

        <p class="login-help">如无法登录，请联系系统管理员。</p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 48px clamp(56px, 19.4vw, 340px) 48px 48px;
  background-color: #eaf3ff;
  background-image: url('@/assets/login-city-background.png');
  background-position: center;
  background-size: cover;
}

.login-card {
  width: 366px;
  padding: 54px 44px 34px;
  border: 1px solid rgba(195, 214, 238, 0.86);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 22px 60px rgba(82, 126, 188, 0.18);
  backdrop-filter: blur(10px);
}

.login-header {
  margin-bottom: 34px;
}

.login-header h1 {
  margin: 0;
  color: #131820;
  font-size: 32px;
  font-weight: 800;
  line-height: 1.35;
  letter-spacing: 0.02em;
}

.login-header p {
  margin: 12px 0 0;
  color: #566475;
  font-size: 16px;
  line-height: 1.6;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.login-form :deep(.el-input__wrapper) {
  min-height: 46px;
  padding: 0 16px;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 0 0 1px #d6dce4 inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #2e82f4 inset;
}

.login-form :deep(.el-input__prefix) {
  margin-right: 9px;
  color: #76818e;
  font-size: 21px;
}

.login-form :deep(.el-input__inner) {
  color: #283442;
  font-size: 16px;
}

.login-form :deep(.el-input__inner::placeholder) {
  color: #8e98a3;
}

.login-button {
  width: 100%;
  min-height: 46px;
  margin-top: 11px;
  border-color: #2479f2;
  border-radius: 27px;
  background: #2479f2;
  box-shadow: 0 10px 24px rgba(36, 121, 242, 0.26);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.login-button:hover,
.login-button:focus {
  border-color: #176de3;
  background: #176de3;
}

.login-help {
  margin: 20px 0 0;
  color: #84909e;
  font-size: 13px;
  text-align: center;
}

@media (max-width: 900px) {
  .login-page {
    justify-content: center;
    padding: 28px 20px;
    background-position: 38% center;
  }

  .login-card {
    width: min(366px, 100%);
    min-height: 0;
    padding: 30px 30px 36px;
    background: rgba(255, 255, 255, 0.94);
  }
}

@media (max-width: 480px) {
  .login-page {
    align-items: flex-end;
    padding: 18px;
  }

  .login-card {
    padding: 26px 24px 30px;
    border-radius: 16px;
  }

  .login-header {
    margin-bottom: 28px;
  }

  .login-header h1 {
    font-size: 30px;
  }

  .login-header p {
    font-size: 15px;
  }
}
</style>
