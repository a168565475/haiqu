import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PermissionCell from './PermissionCell.vue'
import type { CatalogEntry } from '@/types/access'

describe('可配置资源范围', () => {
  const entry = { code: 'workshop_reporting.change_workreport', label: '编辑报工', available: true, scopes: ['MODULE', 'WORKSHOP'] } as CatalogEntry
  it('选择指定车间并打开已有选择，不混入客户范围', async () => {
    const wrapper = mount(PermissionCell, { props: { entry, grants: [{ permission: entry.code, scope: 'MODULE' }] } })
    expect(wrapper.findAll('option').map(o => o.attributes('value'))).toEqual(['MODULE', 'WORKSHOP'])
    await wrapper.get('select').setValue('WORKSHOP')
    expect(wrapper.emitted('change')?.[0]).toEqual([entry.code, ['WORKSHOP']])
    await wrapper.setProps({ grants: [{ permission: entry.code, scope: 'WORKSHOP', resource_ids: ['metal'] }] })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('configure')?.[0]).toEqual([entry.code])
  })
  it('停用角色不能更改或配置范围', () => {
    const wrapper = mount(PermissionCell, { props: { entry, disabled: true, grants: [{ permission: entry.code, scope: 'WORKSHOP', resource_ids: [] }] } })
    expect(wrapper.get('input').attributes('disabled')).toBeDefined()
    expect(wrapper.get('select').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  })
})
