import { computed, onScopeDispose, ref } from 'vue'
import { isNavigationFailure, NavigationFailureType, type RouteLocationNormalized, type Router } from 'vue-router'
import type { useAuthStore } from '@/stores/auth'

type AuthStore = ReturnType<typeof useAuthStore>
const routeApprovals = new WeakMap<object, { store: AuthStore; generation: number }>()

/** Record the identity actually checked by the production guard, before async route resolution. */
export function approveRouteIdentity(route: object, auth: AuthStore) {
  routeApprovals.set(route, { store: auth, generation: auth.identityGeneration })
}

const safeLandingNames = new Set(['home', 'production-overview', 'workshop-workbench', 'login', 'waiting-role'])

export function isCleanIdentityLanding(route: Pick<RouteLocationNormalized, 'name' | 'params' | 'query' | 'hash'>) {
  return safeLandingNames.has(String(route.name)) && !Object.keys(route.params).length
    && !Object.keys(route.query).length && !route.hash
}

export function hasStaleRouteIdentity(route: object, auth: AuthStore) {
  const approval = routeApprovals.get(route)
  return approval?.store === auth && approval.generation !== auth.identityGeneration
}

/** Bind business rendering to the identity that completed navigation, not a live /me response. */
export function useRouteIdentityBoundary(router: Router, auth: ReturnType<typeof useAuthStore>) {
  const initialApproval = routeApprovals.get(router.currentRoute.value)
  const approvedGeneration = ref(initialApproval?.store === auth ? initialApproval.generation : auth.identityGeneration)
  const removeAfterEach = router.afterEach((to, _from, failure) => {
    // A /me change can redirect back to the current home: Vue Router calls that duplicated,
    // without replacing currentRoute. Never grant this exception to an old object URL.
    const duplicateSafeLanding = isNavigationFailure(failure, NavigationFailureType.duplicated)
      && isCleanIdentityLanding(to)
    const approval = routeApprovals.get(to)
    if (duplicateSafeLanding || (!failure && (to.name === 'account-switch-transition'
      || (approval?.store === auth && approval.generation === auth.identityGeneration)))) {
      approvedGeneration.value = auth.identityGeneration
    } else if (!failure && to.meta.requiresAuth) {
      // Another identity can arrive while lazy components / beforeResolve are awaited.
      // Do not bless that old intent with the current generation at commit time.
      void router.replace({ name: !auth.isAuthenticated ? 'login' : auth.waitingForRole ? 'waiting-role' : 'home',
        params: {}, query: {}, hash: '', replace: true }).catch(() => {
        // A refused/failed safe navigation leaves rendering closed for explicit recovery.
      })
    }
  })
  onScopeDispose(removeAfterEach)
  return computed(() => approvedGeneration.value === auth.identityGeneration)
}
