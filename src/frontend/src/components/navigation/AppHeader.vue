<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { SwitchButton } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { getLogoutErrorMessage } from '@/api/auth'
import chevronDownIcon from '@/assets/crm-v2/chevron-down.svg'
import headerLogo from '@/assets/navigation/hitree-header-logo.png'
import GlobalPageTabs from '@/components/navigation/GlobalPageTabs.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const logoutLoading = ref(false)

const visibleName = computed(() => {
  const user = authStore.user
  if (user?.is_superuser) return '超级管理员'
  return user?.employee?.display_name || user?.display_name || user?.username || '用户'
})

async function handleUserCommand(command: string | number | object) {
  if (command !== 'logout' || logoutLoading.value) {
    return
  }

  logoutLoading.value = true
  try {
    await authStore.logout()
    await router.replace({ name: 'login' })
    ElMessage.success('已安全退出')
  } catch (error) {
    ElMessage.error(getLogoutErrorMessage(error))
  } finally {
    logoutLoading.value = false
  }
}
</script>

<template>
  <div class="app-header app-header--page-tabs app-header--crm-v2">
    <div class="app-header__brand" data-app-brand :style="{ '--brand-image': `url(${headerLogo})` }">
      <img :src="headerLogo" alt="HiTree" width="120" height="40" />
    </div>
    <div class="app-header__context">
      <GlobalPageTabs />
    </div>

    <div class="app-header__actions">
      <ElDropdown
        trigger="click"
        placement="bottom-end"
        :disabled="logoutLoading"
        @command="handleUserCommand"
      >
        <button
          type="button"
          class="app-header__user"
          data-current-user
          aria-label="打开用户菜单"
          :aria-busy="logoutLoading"
          :disabled="logoutLoading"
        >
          <span class="app-header__user-name">{{ visibleName }}</span>
          <img class="app-header__user-chevron" :src="chevronDownIcon" alt="" aria-hidden="true" />
        </button>
        <template #dropdown>
          <ElDropdownMenu>
            <ElDropdownItem command="logout" :disabled="logoutLoading" data-logout-action>
              <ElIcon><SwitchButton /></ElIcon>
              <span>{{ logoutLoading ? '正在退出…' : '退出登录' }}</span>
            </ElDropdownItem>
          </ElDropdownMenu>
        </template>
      </ElDropdown>
    </div>
  </div>
</template>

<style scoped lang="scss">
.app-header {
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 0 20px;
  color: var(--erp-color-text-primary);
  font-family: var(--erp-font-body, 'Noto Sans SC', 'Microsoft YaHei', sans-serif);
}

.app-header__brand {
  position: relative;
  flex: none;
  display: flex;
  align-items: center;
  padding-right: 20px;
  border-right: 1px solid var(--erp-color-border);
}
.app-header__brand img {
  display: block;
  width: 120px;
  height: 40px;
  object-fit: contain;
  opacity: 0;
}

// 树形直接滤色原图，保留分面的明暗；字标单独取主题色。
.app-header__brand::before,
.app-header__brand::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 120px;
  height: 40px;
  pointer-events: none;
}
.app-header__brand::before {
  clip-path: inset(0 69% 0 0);
  background: var(--brand-image) center / contain no-repeat;
  filter: var(--erp-logo-filter);
}
.app-header__brand::after {
  clip-path: inset(0 0 0 31%);
  mask: var(--brand-image) center / contain no-repeat;
  background: var(--erp-logo-wordmark-color);
}
.app-header__context {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  align-items: center;
}
.app-header__actions {
  flex: none;
  display: flex;
  align-items: center;
  margin-left: auto;
}
.app-header__user {
  min-width: 0;
  height: 32px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--erp-header-user-color);
  cursor: pointer;
}
.app-header__user:hover:not(:disabled) { background: var(--erp-menu-hover-background); }
.app-header__user:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.app-header__user:disabled { cursor: wait; }
.app-header__user-name {
  max-width: 160px;
  overflow: hidden;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.app-header__user-chevron {
  display: block;
  width: 16px;
  height: 16px;
  flex: none;
}
@media (max-width: 720px) {
  .app-header { gap: 12px; padding: 0 12px; }
  .app-header__brand { padding-right: 12px; }
  .app-header__user-name { max-width: 96px; }
}
</style>
