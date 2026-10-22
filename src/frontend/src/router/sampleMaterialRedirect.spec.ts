import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { router as applicationRouter } from './index'

describe('旧材料填写链接兼容', () => {
  it.each(['/samples/request-1/materials?focus=line-1', { name: 'sample-materials', params: { sampleId: 'request-1' }, query: { tab: 'product' } }])('保留申请并进入编辑材料页签：%s', async location => {
    const old = applicationRouter.getRoutes().find(route => route.name === 'sample-materials')!
    const editor = applicationRouter.getRoutes().find(route => route.name === 'sample-edit')!
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: old.path, name: old.name, redirect: old.redirect! },
      { path: editor.path, name: editor.name, component: { template: '<div>编辑页</div>' } },
    ] })
    await router.push(location)
    expect(router.currentRoute.value.name).toBe('sample-edit')
    expect(router.currentRoute.value.params.sampleId).toBe('request-1')
    expect(router.currentRoute.value.query.tab).toBe('materials')
    if (typeof location === 'string') expect(router.currentRoute.value.query.focus).toBe('line-1')
  })
})
