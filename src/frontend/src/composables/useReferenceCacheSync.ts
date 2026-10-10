import { watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useReferenceOptionsStore } from '@/stores/referenceOptions'

export function useReferenceCacheSync() {
  const auth = useAuthStore()
  const options = useReferenceOptionsStore()
  // 仅处理身份切换；配置按需读取，无定时器或聚焦版本请求。
  watch(() => auth.user?.id, () => options.resetForIdentity(), { flush: 'sync' })
}
