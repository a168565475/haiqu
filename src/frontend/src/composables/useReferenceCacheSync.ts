import { watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useReferenceOptionsStore } from '@/stores/referenceOptions'

export function useReferenceCacheSync() {
  const auth = useAuthStore()
  const options = useReferenceOptionsStore()
  // 同账号版本轮换也清理；普通 /me 不改变此代次。配置仍按需读取，不增加轮询。
  watch(() => auth.identityGeneration, () => options.resetForIdentity(), { flush: 'sync' })
}
