<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { SwitchButton } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { getLogoutErrorMessage } from '@/api/auth'
import avatarFrame from '@/assets/crm-v2/avatar.svg'
import bellIcon from '@/assets/crm-v2/bell.svg'
import chevronDownIcon from '@/assets/crm-v2/chevron-down.svg'
import globalSearchIcon from '@/assets/crm-v2/global-search.svg'
import GlobalPageTabs from '@/components/navigation/GlobalPageTabs.vue'
import { useAuthStore } from '@/stores/auth'

withDefaults(
  defineProps<{
    compact?: boolean
  }>(),
  {
    compact: false,
  },
)

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const logoutLoading = ref(false)

const headerSearchPlaceholder = computed(() => {
  if (route.name === 'customers') return '搜索客户、联系人、订单号'
  return typeof route.meta.headerSearchPlaceholder === 'string'
    ? route.meta.headerSearchPlaceholder
    : '搜索客户、联系人、询盘'
})

const visibleName = computed(() => {
  const user = authStore.user
  if (user?.is_superuser) return '超级管理员'
  return user?.employee?.display_name || user?.display_name || user?.username || '用户'
})

const avatarText = computed(() => {
  return Array.from(visibleName.value.trim())[0]?.toUpperCase() || '用'
})

function showUnavailableFeature() {
  ElMessage.info('该功能尚未开放。')
}

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
  <div class="app-header app-header--page-tabs app-header--crm-v2" :class="{ 'app-header--compact': compact }">
    <div class="app-header__context">
      <GlobalPageTabs />
    </div>

    <div class="app-header__search-shell">
      <img :src="globalSearchIcon" alt="" aria-hidden="true" />
      <input
        class="app-header__search"
        type="search"
        :placeholder="headerSearchPlaceholder"
        aria-label="全局搜索（功能尚未开放）"
        @keyup.enter.prevent="showUnavailableFeature"
      />
    </div>
    <div class="app-header__actions">
      <button
        type="button"
        class="app-header__icon-action app-header__help"
        aria-label="帮助功能尚未接入"
        title="帮助功能尚未接入"
        @click="showUnavailableFeature"
      >
        ?
      </button>
      <button
        type="button"
        class="app-header__icon-action"
        aria-label="通知功能尚未接入"
        title="通知功能尚未接入"
        @click="showUnavailableFeature"
      >
        <img :src="bellIcon" alt="" aria-hidden="true" />
      </button>

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
          <span class="app-header__avatar" aria-hidden="true">
            <img :src="avatarFrame" alt="" />
            <span>{{ avatarText }}</span>
          </span>
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
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 68px 0 24px;
  color: #303238;
}

.app-header__context {
  flex: none;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 20px;
}

.app-header__icon-action img,
.app-header__user-chevron {
  display: block;
}

.app-header__search {
  width: 280px;
  height: 32px;
  flex: none;
  margin-left: auto;
  padding: 0 12px;
  border: 1px solid #d9dce2;
  border-radius: 8px;
  outline: none;
  color: #60636b;
  background: #fff;
  font: inherit;
  font-size: 14px;
}

.app-header__search:disabled {
  cursor: default;
  opacity: 1;
  -webkit-text-fill-color: #8b8f97;
}

.app-header__search::placeholder {
  color: #8b8f97;
  opacity: 1;
}

.app-header__actions {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-left: 24px;
}

.app-header__icon-action {
  width: 24px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  color: #4f535b;
  background: transparent;
}

.app-header__icon-action:disabled {
  cursor: default;
  opacity: 1;
}

.app-header__help {
  font-size: 15px;
  font-weight: 500;
}

.app-header__user {
  min-width: 0;
  height: 40px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
}

.app-header__user:focus-visible {
  outline: 2px solid #409eff;
  outline-offset: 2px;
}

.app-header__user:disabled {
  cursor: wait;
}

.app-header__avatar {
  width: 32px;
  height: 32px;
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #3f4248;
  background: #f1f2f4;
  font-size: 14px;
  font-weight: 600;
}

.app-header__avatar img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.app-header__avatar span {
  position: relative;
}

.app-header__user-name {
  max-width: 120px;
  overflow: hidden;
  color: #4b4f57;
  font-size: 14px;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-header--compact {
  padding-right: 128px;
}

.app-header--compact .app-header__search {
  width: 220px;
}

.app-header--compact .app-header__user-name {
  display: none;
}

.app-header--crm-v2 {
  position: relative;
  gap: 0;
  padding: 0;
  color: #1f1d18;
  font-family: var(--erp-font-body, 'Noto Sans SC', 'Microsoft YaHei', sans-serif);
}

.app-header--crm-v2 .app-header__context {
  position: absolute;
  top: 0;
  left: 28px;
  height: 64px;
  gap: 18px;
}

.app-header__search-shell {
  position: absolute;
  top: 14px;
  right: 344px;
  width: 310px;
  height: 36px;
  display: flex;
  box-sizing: border-box;
  align-items: center;
  gap: 10px;
  padding-left: 12px;
  overflow: hidden;
  border: 1px solid #ddd6c9;
  border-radius: 5px;
  background: var(--erp-surface-background);
}

.app-header__search-shell > img {
  width: 16px;
  height: 16px;
  flex: none;
}

.app-header--crm-v2 .app-header__search {
  width: 100%;
  height: 34px;
  min-width: 0;
  margin: 0;
  padding: 0 10px 0 0;
  border: 0;
  border-radius: 0;
  color: #1f1d18;
  background: transparent;
  font-size: 12px;
  line-height: 18px;
}

.app-header--crm-v2 .app-header__search:focus-visible {
  outline: none;
}

.app-header__search-shell:focus-within {
  box-shadow: 0 0 0 2px rgba(56, 152, 236, 0.28);
}

.app-header--compact .app-header__search-shell,
.app-header--compact > .app-header__search {
  display: none;
}

.app-header--crm-v2 .app-header__search::placeholder {
  color: #968f84;
}

.app-header--crm-v2 .app-header__actions {
  position: absolute;
  top: 0;
  right: 38px;
  width: 268px;
  height: 64px;
  justify-content: space-between;
  gap: 0;
  margin: 0;
}

.app-header--crm-v2 .app-header__icon-action {
  width: 24px;
  height: 32px;
  flex: none;
  color: #6f6a61;
  cursor: pointer;
}

.app-header--crm-v2 .app-header__icon-action img {
  width: 17px;
  height: 17px;
}

.app-header--crm-v2 .app-header__user {
  width: 168px;
  height: 40px;
  flex: none;
  gap: 12px;
  border-radius: 5px;
}

.app-header--crm-v2 .app-header__avatar {
  position: relative;
  color: #c84e28;
  background: transparent;
  font-size: 12px;
  font-weight: 500;
}

.app-header--crm-v2 .app-header__user-name {
  width: 96px;
  color: #1f1d18;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
}

.app-header__user-chevron {
  width: 16px;
  height: 16px;
  flex: none;
  margin-left: -4px;
}

// 页面标签、搜索和账号操作共用一排；只有标签列表承担横向滚动。
.app-header.app-header--page-tabs {
  height: 64px;
  gap: 24px;
  padding: 0 38px 0 24px;
  background: var(--erp-surface-background);
  color: #1f1d18;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}
.app-header--page-tabs .app-header__context {
  position: static;
  flex: 1;
  min-width: 0;
  height: 64px;
  gap: 12px;
}
.app-header--page-tabs .app-header__search-shell {
  position: static;
  width: 280px;
  height: 32px;
  flex: none;
}
.app-header--page-tabs .app-header__search {
  height: 32px;
  margin-left: 0;
  border-radius: 5px;
}
.app-header--page-tabs .app-header__actions {
  position: static;
  width: 268px;
  height: 64px;
  flex: none;
  justify-content: space-between;
  gap: 0;
  margin: 0;
}
.app-header--page-tabs .app-header__icon-action { width: 32px; height: 32px; }
.app-header--page-tabs .app-header__user { height: 32px; }

@media (max-width: 900px) {
  .app-header {
    padding-right: 24px;
  }

  .app-header__search-shell,
  .app-header__search {
    display: none;
  }

  .app-header__actions {
    margin-left: auto;
  }
}

@media (max-width: 480px) {
  .app-header {
    gap: 12px;
    padding: 0 16px;
  }

  .app-header__context {
    gap: 12px;
  }

  .app-header__actions {
    margin-left: auto;
    gap: 8px;
  }

  .app-header__icon-action {
    display: none;
  }

  .app-header__user-name {
    max-width: 88px;
  }
}
</style>
