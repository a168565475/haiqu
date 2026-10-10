import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import ContactTable from './ContactTable.vue'
import type { ContactListItem } from '@/types/contact'

const row: ContactListItem = {
  id: 'contact-1',
  customer: { id: 'customer-1', account_code: 'CUS-001', account_name: '测试客户' },
  display_name: '张三',
  english_name: 'Zhang San',
  position_title: '采购经理',
  department_name: '采购部',
  preferred_language_code: 'zh-CN',
  timezone_code: 'Asia/Shanghai',
  is_key_contact: true,
  is_primary_contact: true,
  status: 'ACTIVE',
  status_display: '在职',
  left_effective_date: null,
  marketing_opt_out: false,
  open_task_count: 0,
  methods: [{
    id: 'method-1', method_type: 'EMAIL', method_type_display: '邮箱',
    display_value: 'zhangsan@example.com', masked_value: 'z***@example.com',
    is_primary: true, is_preferred: true, verification_status: 'UNVERIFIED',
    archived_at: null, updated_at: '2026-08-22T00:00:00Z',
  }, {
    id: 'method-2', method_type: 'MOBILE', method_type_display: '手机',
    display_value: '13812340000', masked_value: '138****0000',
    is_primary: false, is_preferred: false, verification_status: 'UNVERIFIED',
    archived_at: null, updated_at: '2026-08-22T00:00:00Z',
  }, {
    id: 'method-3', method_type: 'PHONE', method_type_display: '电话',
    display_value: '02112340000', masked_value: '021****0000',
    is_primary: false, is_preferred: false, verification_status: 'UNVERIFIED',
    archived_at: null, updated_at: '2026-08-22T00:00:00Z',
  }],
  active_roles: [{ id: 'role-1', role_type: 'BUYER', role_type_display: '采购联系人' }],
  last_interaction: null,
  archived_at: null,
  created_at: '2026-08-22T00:00:00Z',
  updated_at: '2026-08-22T00:00:00Z',
}

describe('ContactTable', () => {
  it('展示完整联系方式和关键联系人标记', async () => {
    const wrapper = mount(ContactTable, {
      props: {
        rows: [row], loading: false, showCustomer: true,
        visibleColumns: ['name', 'customer', 'position', 'roles', 'methods', 'interaction', 'status'],
      },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()
    await nextTick()

    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('主')
    expect(wrapper.text()).toContain('zhangsan@example.com')
    expect(wrapper.text()).toContain('13812340000')
    expect(wrapper.text()).toContain('02112340000')
    expect(wrapper.text()).not.toContain('z***@example.com')
  })

  it('取消左侧固定列，且所有操作统一收进更多菜单', async () => {
    const wrapper = mount(ContactTable, {
      props: {
        rows: [row], loading: false, showCustomer: false, canChange: true, canLeave: true,
        visibleColumns: ['name', 'position', 'roles', 'methods'],
      },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()
    await nextTick()

    const tableColumns = wrapper.findAllComponents({ name: 'ElTableColumn' })
    expect(tableColumns[0].props('fixed')).toBe(false)
    expect(tableColumns[1].props('fixed')).toBe(false)
    expect(wrapper.findAllComponents({ name: 'ElDropdown' })).toHaveLength(1)
    expect(wrapper.text()).toContain('更多')
    expect(wrapper.text()).not.toContain('查看')
    expect(wrapper.text()).not.toContain('编辑')
  })

  it('离职状态不显示离职操作', () => {
    const wrapper = mount(ContactTable, {
      props: {
        rows: [{ ...row, status: 'LEFT', status_display: '已离职' }], loading: false,
        showCustomer: false, visibleColumns: ['name', 'status'],
      },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.findAll('button').some((button) => button.text() === '离职')).toBe(false)
  })

  it('V2 客户联系人表格保留完整列并显示直接操作', async () => {
    const wrapper = mount(ContactTable, {
      props: {
        rows: [row], loading: false, showCustomer: false, canChange: true, canLeave: true,
        visibleColumns: ['name', 'position', 'department', 'roles', 'methods', 'interaction', 'status', 'relationship'],
        v2: true,
      },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()
    await nextTick()

    expect(wrapper.classes()).toContain('contact-table--v2')
    expect(wrapper.text()).toContain('部门')
    expect(wrapper.text()).toContain('关系与偏好')
    expect(wrapper.text()).toContain('关键联系人')
    expect(wrapper.text()).toContain('查看')
    expect(wrapper.text()).toContain('编辑')
    expect(wrapper.find('.more-trigger').attributes('aria-label')).toBe('更多联系人操作')
  })
})
