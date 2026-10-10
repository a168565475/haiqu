import { computed, onScopeDispose, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { useReferenceOptionsStore } from '@/stores/referenceOptions'
import type { PublishedOption } from '@/types/referenceData'

export function useOptions(typeCode: MaybeRefOrGetter<string>, currentId?: MaybeRefOrGetter<string | undefined>) {
  const store = useReferenceOptionsStore()
  const options = ref<PublishedOption[]>([])
  const loading = ref(false)
  const error = ref<unknown>(null)
  let requestNumber = 0
  watch(() => store.identityGeneration, () => { requestNumber += 1; options.value = []; loading.value = false })
  onScopeDispose(() => { requestNumber += 1 })
  async function load(force = false): Promise<PublishedOption[]> {
    const currentRequest = ++requestNumber
    loading.value = true
    error.value = null
    try {
      const values = await store.load(toValue(typeCode), currentId ? toValue(currentId) : undefined, force)
      if (currentRequest === requestNumber) options.value = values
      return values
    } catch (loadError) {
      if (currentRequest === requestNumber) error.value = loadError
      throw loadError
    } finally {
      if (currentRequest === requestNumber) loading.value = false
    }
  }
  const reload = () => load(true)
  return { options, loading, error, configVersion: computed(() => store.configVersion), load, reload }
}
