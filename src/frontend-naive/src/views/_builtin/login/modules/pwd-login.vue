<script setup lang="ts">
import { computed, reactive } from 'vue';
import { $t } from '@/locales';
import { useAuthStore } from '@/store/modules/auth';
import { useNaiveForm } from '@/hooks/common/form';

defineOptions({ name: 'PwdLogin' });

const authStore = useAuthStore();
const { formRef, validate } = useNaiveForm();
const model = reactive({ userName: '', password: '' });
const rules = computed(() => ({
  userName: [{ required: true, whitespace: true, message: '请输入 ERP 用户名', trigger: 'blur' },
    { max: 150, message: '用户名不能超过150个字符', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' },
    { max: 128, message: '密码不能超过128个字符', trigger: 'blur' }]
}));

async function handleSubmit() {
  if (authStore.loginLoading) return;
  try {
    await validate();
  } catch (error) {
    if (Array.isArray(error)) return;
    throw error;
  }
  await authStore.login(model.userName, model.password);
}
</script>

<template>
  <NForm ref="formRef" :model="model" :rules="rules" size="large" :show-label="false" @submit.prevent="handleSubmit">
    <NText depth="3" tag="p" class="mb-20px">使用 ERP 账号登录</NText>
    <NAlert v-if="authStore.loginError" type="error" class="mb-20px" :show-icon="true">
      {{ authStore.loginError }}
    </NAlert>
    <NFormItem path="userName">
      <NInput
        v-model:value="model.userName"
        :placeholder="$t('page.login.common.userNamePlaceholder')"
        :input-props="{ autocomplete: 'username' }"
        :maxlength="150"
        :disabled="authStore.loginLoading"
      />
    </NFormItem>
    <NFormItem path="password">
      <NInput
        v-model:value="model.password"
        type="password"
        show-password-on="click"
        :placeholder="$t('page.login.common.passwordPlaceholder')"
        :input-props="{ autocomplete: 'current-password' }"
        :maxlength="128"
        :disabled="authStore.loginLoading"
      />
    </NFormItem>
    <NButton type="primary" attr-type="submit" size="large" round block :loading="authStore.loginLoading">
      登录
    </NButton>
  </NForm>
</template>
