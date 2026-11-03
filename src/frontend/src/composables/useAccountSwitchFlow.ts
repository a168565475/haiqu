import { isAxiosError } from 'axios'
import { ElMessageBox } from 'element-plus'
import { onScopeDispose, ref } from 'vue'
import { isNavigationFailure, NavigationFailureType, useRouter, type Router } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

export type AccountSwitchPhase = 'idle' | 'confirming' | 'leaving' | 'switching' | 'returning' | 'verifying' | 'landing'
type Operation = 'switch' | 'return' | 'verify'
type AuthStore = ReturnType<typeof useAuthStore>
type ConfirmTransition = (operation: Operation) => Promise<boolean>
const transitionRouteName = 'account-switch-transition'
const homeRouteNames = new Set(['home', 'production-overview', 'workshop-workbench'])

async function confirmTransition(operation: Operation): Promise<boolean> {
  const action = operation === 'switch' ? '切换员工' : operation === 'return' ? '返回管理员' : '重新核验身份'
  try {
    await ElMessageBox.confirm(
      `将先离开当前页面，再${action}。尚未保存到服务端的内容不会随身份移交；按账号保存的草稿仍归原账号，历史待核对请求不会自动重提。页面自身的离开确认仍会执行。是否继续？`,
      action,
      { type: 'warning', confirmButtonText: `继续${action}`, cancelButtonText: '留在当前页面', distinguishCancelAndClose: true },
    )
    return true
  } catch (reason) {
    if (reason === 'cancel' || reason === 'close') return false
    throw reason
  }
}

function snapshot(auth: AuthStore) {
  return { userId: auth.user?.id ?? null, version: auth.identityVersion,
    generation: auth.identityGeneration, requestGeneration: auth.identityRequestGeneration }
}
function sameContext(auth: AuthStore, before: ReturnType<typeof snapshot>) {
  return before.userId === (auth.user?.id ?? null) && before.version === auth.identityVersion
    && before.generation === auth.identityGeneration && before.requestGeneration === auth.identityRequestGeneration
}
function operationAllowed(auth: AuthStore, operation: Operation) {
  if (auth.identityTransitionPending || auth.checking) return false
  return operation === 'switch' ? auth.canSwitchAccount : operation === 'return' ? auth.canReturnAdmin : true
}
function errorMessage(error: unknown, operation: Operation, ready: boolean): string {
  if (!ready) return '身份操作结果尚未确认。业务请求已暂停，请点击“重新核验身份”；不会自动重试切换或返回。'
  if (isAxiosError(error)) {
    const code = error.response?.data?.error?.code
    if (code === 'IDENTITY_VERSION_REQUIRED' || code === 'IDENTITY_VERSION_CONFLICT') {
      return '当前身份已变化，请重新核验身份后再选择员工；本次操作不会自动重试。'
    }
    if (error.response?.status === 403 || error.response?.status === 404) {
      return operation === 'switch' ? '员工状态或切换权限已变化，请重新查询员工后再试。' : '当前无法返回管理员，请重新核验身份后再试。'
    }
  }
  return operation === 'verify' ? '暂时无法核验身份，请稍后主动重试。' : '身份操作未完成，请检查当前身份后主动重试。'
}

// 独立工厂便于用真实内存路由测试导航失败；生产只能在 App 全局控制器创建一份。
export function createAccountSwitchFlow(auth: AuthStore, router: Router, confirm: ConfirmTransition = confirmTransition) {
  const busy = ref(false)
  const phase = ref<AccountSwitchPhase>('idle')
  const error = ref('')
  let disposed = false
  function isTransitionPage() {
    const route = router.currentRoute.value
    return route.name === transitionRouteName && !Object.keys(route.query).length && !route.hash && !Object.keys(route.params).length
  }
  async function perform(operation: Operation, employeeId?: string): Promise<boolean> {
    // 不排队、不替换正在执行的意图；覆盖确认、旧页离开、网络写和新身份落点的全程互斥。
    if (busy.value || disposed) return false
    error.value = ''
    if (!operationAllowed(auth, operation)) {
      error.value = '当前身份尚不可执行此操作，请先完成身份核验。'
      return false
    }
    const before = snapshot(auth)
    const originalPath = router.currentRoute.value.fullPath
    busy.value = true
    try {
      phase.value = 'confirming'
      if (!await confirm(operation)) return false
      if (disposed) return false
      if (!sameContext(auth, before) || !operationAllowed(auth, operation)
        || router.currentRoute.value.fullPath !== originalPath) {
        error.value = '当前身份或页面已变化，本次操作已取消，请在确认当前页面后重新操作。'
        return false
      }
      phase.value = 'leaving'
      // 绝不在这里绕过 beforeRouteLeave；导航中止通常 resolve NavigationFailure，不会 throw。
      const failure = await router.replace({ name: transitionRouteName })
      if (disposed) return false
      if ((failure && !(isNavigationFailure(failure, NavigationFailureType.duplicated) && isTransitionPage())) || !isTransitionPage()) {
        error.value = '当前页面未允许离开，本次身份操作已取消。请先处理页面提示，再重新发起操作；后续导航不会恢复本次意图。'
        return false
      }
      if (!sameContext(auth, before) || !operationAllowed(auth, operation)) {
        error.value = '离开页面期间身份已变化，本次操作已取消，请重新核验后再试。'
        return false
      }
      if (operation === 'verify') {
        phase.value = 'verifying'
        const appliedGeneration = await auth.initialize(true)
        if (disposed) return false
        if (appliedGeneration === undefined || appliedGeneration !== auth.authenticationGeneration || !auth.identityReady) {
          error.value = '核验结果已失效或被更新，请重新核验身份；未执行身份切换。'
          return false
        }
      } else {
        phase.value = operation === 'switch' ? 'switching' : 'returning'
        if (operation === 'switch') await auth.switchAccount(employeeId!)
        else await auth.returnAdmin()
        if (disposed) return false
        const expectedUser = operation === 'switch'
          ? auth.user?.employee?.id === employeeId && auth.accountSwitch?.active === true
          : auth.user?.username === 'admin' && auth.user.is_superuser && auth.accountSwitch?.active !== true
        if (!auth.identityReady || auth.identityGeneration === before.generation || !expectedUser) {
          auth.requireIdentityRevalidation()
          error.value = '未能确认目标身份，业务请求已暂停。请重新核验身份；不会自动重试本次操作。'
          return false
        }
      }
      const committed = snapshot(auth)
      const destination = !auth.isAuthenticated ? 'login' : auth.waitingForRole ? 'waiting-role' : 'home'
      phase.value = 'landing'
      // 不读取旧 redirect/params/query，不复用原页面；home 的既有权限分流仍然生效。
      const landingFailure = await router.replace({ name: destination, query: {}, hash: '' })
      if (disposed) return false
      const landed = router.currentRoute.value
      const expectedLanding = destination === 'home' ? homeRouteNames.has(String(landed.name)) : landed.name === destination
      if ((landingFailure && !isNavigationFailure(landingFailure, NavigationFailureType.duplicated))
        || !expectedLanding || Object.keys(landed.query).length || landed.hash || !sameContext(auth, committed)) {
        error.value = '身份状态已更新，但安全页面未能打开。请核对上方当前身份，再主动进入首页；不要重提刚才的身份操作。'
        return false
      }
      return true
    } catch (reason) {
      if (!disposed) error.value = phase.value === 'landing'
        ? '身份状态已更新，但安全页面暂不可用。请核对当前身份后主动进入首页，不要重复切换。'
        : errorMessage(reason, operation, auth.identityReady)
      return false
    } finally {
      phase.value = 'idle'
      busy.value = false
    }
  }
  return {
    busy, phase, error,
    switchAccount: (employeeId: string) => perform('switch', employeeId),
    returnAdmin: () => perform('return'),
    verifyIdentity: () => perform('verify'),
    dispose: () => { disposed = true },
  }
}

export function useAccountSwitchFlow() {
  const flow = createAccountSwitchFlow(useAuthStore(), useRouter())
  onScopeDispose(flow.dispose)
  return flow
}
