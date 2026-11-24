import { computed, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { defineStore } from 'pinia';
import { useLoading } from '@sa/hooks';
import { localStg } from '@/utils/storage';
import { fetchErpUserSession, loginErp, logoutErp } from '@/service/api/erp-auth';
import type { ErpSession } from '@/typings/erp-auth';
import { $t } from '@/locales';
import { useRouterPush } from '@/hooks/common/router';
import { SetupStoreId } from '@/enum';
import { useRouteStore } from '../route';
import { useTabStore } from '../tab';
import { clearAuthStorage } from './shared';

export const useAuthStore = defineStore(SetupStoreId.Auth, () => {
  const route = useRoute();
  const routeStore = useRouteStore();
  const tabStore = useTabStore();
  const { toLogin, redirectFromLogin } = useRouterPush(false);
  const { loading: loginLoading, startLoading, endLoading } = useLoading();
  const sessionInitialized = ref(false);
  const authenticated = ref(false);
  const loginError = ref('');
  const logoutLoading = ref(false);
  let sessionPromise: Promise<void> | undefined;

  const userInfo: Api.Auth.UserInfo = reactive({ userId: '', userName: '', roles: [], buttons: [] });
  const isLogin = computed(() => authenticated.value);
  const isStaticSuper = computed(() =>
    import.meta.env.VITE_AUTH_ROUTE_MODE === 'static' && userInfo.roles.includes(import.meta.env.VITE_STATIC_SUPER_ROLE)
  );

  function applySession(session: ErpSession) {
    authenticated.value = session.authenticated;
    Object.assign(userInfo, session.authenticated ? {
      userId: String(session.user.id),
      userName: session.user.display_name || session.user.username,
      roles: session.user.is_superuser ? [import.meta.env.VITE_STATIC_SUPER_ROLE] : [],
      buttons: session.user.permissions
    } : { userId: '', userName: '', roles: [], buttons: [] });
  }

  function recordUserId() {
    if (userInfo.userId) localStg.set('lastLoginUserId', userInfo.userId);
  }

  function checkTabClear() {
    const lastLoginUserId = localStg.get('lastLoginUserId');
    const changed = !lastLoginUserId || lastLoginUserId !== userInfo.userId;
    if (changed) {
      localStg.remove('globalTabs');
      tabStore.clearAuthTabs();
    }
    localStg.remove('lastLoginUserId');
    return changed;
  }

  /** 服务端已确认会话失效后的本地清理；主动退出应调用 logout。 */
  async function resetStore() {
    const redirect = route.fullPath;
    recordUserId();
    tabStore.cacheTabs();
    clearAuthStorage();
    applySession({ authenticated: false, user: null });
    sessionInitialized.value = true;
    await routeStore.resetStore();
    if (route.name !== 'login') await toLogin(undefined, redirect);
  }

  async function login(userName: string, password: string, redirect = true) {
    if (loginLoading.value) return;
    startLoading();
    loginError.value = '';
    try {
      const session = await loginErp(userName, password);
      applySession(session);
      sessionInitialized.value = true;
      clearAuthStorage();
      if (checkTabClear()) await routeStore.resetStore();
      await routeStore.initAuthRoute();
      // 清理旧页签不改变本次登录的目标地址。
      await redirectFromLogin(redirect);
      window.$notification?.success({
        title: $t('page.login.common.loginSuccess'),
        content: $t('page.login.common.welcomeBack', { userName: userInfo.userName }),
        duration: 4500
      });
    } catch (error) {
      loginError.value = error instanceof Error ? error.message : '登录失败，请稍后重试。';
    } finally {
      endLoading();
    }
  }

  async function logout() {
    if (logoutLoading.value) return false;
    logoutLoading.value = true;
    try {
      await logoutErp();
      await resetStore();
      return true;
    } catch (error) {
      window.$message?.error(error instanceof Error ? error.message : '退出失败，请重试。');
      return false;
    } finally {
      logoutLoading.value = false;
    }
  }

  async function initUserInfo(force = false) {
    if (sessionInitialized.value && !force) return;
    if (sessionPromise) return sessionPromise;
    // 旧演示 Token 不能代表 ERP 登录状态，也不能继续发往演示服务。
    clearAuthStorage();
    sessionPromise = (async () => {
      const previousUserId = userInfo.userId;
      const previousRoles = userInfo.roles.join(',');
      try {
        applySession(await fetchErpUserSession());
        loginError.value = '';
      } catch (error) {
        // 网络失败不能证明会话失效；保留已知身份，由业务请求显示连接错误。
        loginError.value = error instanceof Error ? error.message : '无法读取登录状态，请重试。';
      } finally {
        sessionInitialized.value = true;
      }
      // 原 ERP 与本前端共享 Cookie，换账号后不能沿用旧身份的页签和路由。
      if (previousUserId && (previousUserId !== userInfo.userId || previousRoles !== userInfo.roles.join(','))) {
        localStg.set('lastLoginUserId', previousUserId);
        localStg.remove('globalTabs');
        tabStore.clearAuthTabs();
        await routeStore.resetStore();
      }
    })();
    try {
      await sessionPromise;
    } finally {
      sessionPromise = undefined;
    }
  }

  return { userInfo, isStaticSuper, isLogin, loginLoading, loginError, resetStore, login, logout, initUserInfo };
});
