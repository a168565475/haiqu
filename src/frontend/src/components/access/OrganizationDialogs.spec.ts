import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElSelect } from 'element-plus'
import DepartmentMaintenanceDialog from './DepartmentMaintenanceDialog.vue'
import EmployeeDepartmentsDialog from './EmployeeDepartmentsDialog.vue'
import * as api from '@/api/access'
import type { AccessDepartment, AccessEmployee } from '@/types/access'

vi.mock('@/api/access', () => ({ createDepartment: vi.fn(), updateDepartment: vi.fn(), getEmployeeDepartments: vi.fn(), assignDepartments: vi.fn(), accessError: () => '版本已变化，请重新读取' }))
vi.mock('element-plus', async original => ({ ...await original<object>(), ElMessage: { success: vi.fn() } }))
const stub = { props:['modelValue'], template:'<section v-if="modelValue" role="dialog"><slot/><slot name="footer"/></section>' }
const global = { stubs:{AppWindowDialog:stub} }
const departments: AccessDepartment[] = [
  { id:'root', unit_code:'HAIQU', unit_name:'海趣', parent_id:null, sort_order:0, status:'ACTIVE', etag:'root-v1' },
  { id:'production', unit_code:'DEPT_PRODUCTION', unit_name:'生产部', parent_id:'root', sort_order:40, status:'ACTIVE', etag:'dep-v1' },
  { id:'support', unit_code:'DEPT_SUPPORT', unit_name:'技术支持', parent_id:'root', sort_order:110, status:'ACTIVE', etag:'support-v1' },
]
const employee = { id:'employee', display_name:'员工', status:'ACTIVE', etag:'old-employee-version' } as AccessEmployee
const history = { employee_id:'employee', etag:'current-employee-version', departments:[
  { id:'assignment', department_id:'production', department_name:'生产部', is_primary:true, position_title:'主任', effective_from:'2026-01-01T00:00:00Z', effective_to:null },
  { id:'history', department_id:'support', department_name:'技术支持', is_primary:true, position_title:'历史岗位', effective_from:'2024-01-01T00:00:00Z', effective_to:'2025-01-01T00:00:00Z' },
] }
beforeEach(() => vi.resetAllMocks())
const button = (wrapper:ReturnType<typeof mount>, name:string) => wrapper.findAll('button').find(b=>b.text()===name)!

describe('部门维护及员工历史', () => {
  it('新部门校验缺失编码，现有部门保持稳定编码并携带ETag保存', async () => {
    vi.mocked(api.updateDepartment).mockResolvedValue(departments[1]!)
    const wrapper = mount(DepartmentMaintenanceDialog,{props:{modelValue:true,departments},global})
    await button(wrapper,'保存部门').trigger('click')
    expect(api.createDepartment).not.toHaveBeenCalled()
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', 'production'); await flushPromises()
    expect(wrapper.get('input[maxlength="50"]').attributes('disabled')).toBeDefined()
    await wrapper.get('input[maxlength="200"]').setValue('生产组织')
    await button(wrapper,'保存部门').trigger('click'); await flushPromises()
    expect(api.updateDepartment).toHaveBeenCalledWith(expect.objectContaining({id:'production',etag:'dep-v1'}),{unit_name:'生产组织',sort_order:40,status:'ACTIVE'})
    wrapper.unmount()
  })
  it('员工当前关系与历史分开显示，保存采用读取历史时的版本且不覆盖历史行', async () => {
    vi.mocked(api.getEmployeeDepartments).mockResolvedValue(history)
    vi.mocked(api.assignDepartments).mockResolvedValue(history)
    const wrapper = mount(EmployeeDepartmentsDialog,{props:{employee,departments},global}); await flushPromises()
    expect(wrapper.text()).toContain('历史岗位')
    expect(wrapper.findAll('input[type="checkbox"]').map(b=>(b.element as HTMLInputElement).checked)).toEqual([true,false])
    await wrapper.findAll('input[type="checkbox"]')[1]!.setValue(true)
    await button(wrapper,'保存员工部门').trigger('click'); await flushPromises()
    expect(api.assignDepartments).toHaveBeenCalledWith(employee,[{department_id:'production',position_title:'主任',is_primary:true},{department_id:'support',position_title:'',is_primary:false}],'current-employee-version')
    wrapper.unmount()
  })
  it('历史读取失败时禁用保存，禁止以空数组覆盖原归属', async () => {
    vi.mocked(api.getEmployeeDepartments).mockRejectedValue(new Error('offline'))
    const wrapper = mount(EmployeeDepartmentsDialog,{props:{employee,departments},global}); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('版本已变化')
    expect(button(wrapper,'保存员工部门').attributes('disabled')).toBeDefined()
    expect(api.assignDepartments).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
