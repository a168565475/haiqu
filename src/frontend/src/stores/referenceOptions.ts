import { defineStore } from 'pinia'
import { fetchPublishedOptions } from '@/api/referenceData'
import type { PublishedOption, PublishedOptionsResponse } from '@/types/referenceData'

const requests = new WeakMap<object, Map<string, Promise<PublishedOptionsResponse>>>()
export const useReferenceOptionsStore = defineStore('referenceOptions', {
  state: () => ({ configVersion: null as number | null, cacheGeneration: 0, identityGeneration: 0 }),
  actions: {
    async load(typeCode: string, currentId?: string, _force = false): Promise<PublishedOption[]> {
      const code = typeCode.trim().toUpperCase()
      if (!code) throw new Error('字典类型编码不能为空。')
      const selected = currentId?.trim() || ''
      const generation = this.cacheGeneration
      let pending = requests.get(this)
      if (!pending) { pending = new Map(); requests.set(this, pending) }
      const key = `${code}:${selected}`
      let request = pending.get(key)
      if (!request) {
        request = fetchPublishedOptions(code, selected || undefined)
        pending.set(key, request)
      }
      try {
        const response = await request
        if (generation !== this.cacheGeneration) throw new Error('配置读取上下文已变化，请重新打开页面。')
        // 仅兼容原有“是否已有发布配置”的展示判断，不再请求或比较版本。
        this.configVersion = response.meta.config_version
        return response.data
      } finally {
        if (pending.get(key) === request) pending.delete(key)
      }
    },
    invalidate(_typeCode?: string) {
      this.cacheGeneration += 1
      this.configVersion = null
      requests.get(this)?.clear()
    },
    resetForIdentity() {
      this.identityGeneration += 1
      this.invalidate()
    },
  },
})
