import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadReportEmployees, saveReportEmployees } from './reportEmployeeMemory'

const scope = { workshop_id: 'memory-workshop', craft_id: 'memory-craft' }
const key = (userId = 1, selected = scope) => `haiqu-mobile:report-employees:${JSON.stringify([userId, selected.workshop_id, selected.craft_id])}`
const keys = [key(), key(2), key(1, { ...scope, workshop_id: 'other-workshop' }), key(1, { ...scope, craft_id: 'other-craft' })]
const cleanup = () => { for (const item of keys) localStorage.removeItem(item) }
beforeEach(cleanup)
afterEach(() => { vi.restoreAllMocks(); cleanup() })

describe('报工员工本地记忆', () => {
  it('没有记录返回空映射，保存按约定键写入完整映射', () => {
    expect(loadReportEmployees(1, scope)).toEqual({})
    saveReportEmployees(1, scope, { 'work-one': 'employee-one' })
    expect(JSON.parse(localStorage.getItem(key())!)).toEqual({ 'work-one': 'employee-one' })
    expect(loadReportEmployees(1, scope)).toEqual({ 'work-one': 'employee-one' })
    saveReportEmployees(1, scope, { 'work-two': 'employee-two' })
    expect(loadReportEmployees(1, scope)).toEqual({ 'work-two': 'employee-two' })
  })
  it('账号、车间及工艺分别隔离，不能串用另一个范围的员工', () => {
    saveReportEmployees(1, scope, { work: 'employee-one' })
    expect(loadReportEmployees(2, scope)).toEqual({})
    expect(loadReportEmployees(1, { ...scope, workshop_id: 'other-workshop' })).toEqual({})
    expect(loadReportEmployees(1, { ...scope, craft_id: 'other-craft' })).toEqual({})
    saveReportEmployees(2, scope, { work: 'employee-two' })
    expect(loadReportEmployees(1, scope)).toEqual({ work: 'employee-one' })
    expect(loadReportEmployees(2, scope)).toEqual({ work: 'employee-two' })
  })
  it.each(['', '{broken', 'null', '[]', '"text"', '1', '{"work":1}', '{"work":null}', '{"work":{}}'])('损坏或不合约的存储值抛出错误：%s', (saved) => {
    localStorage.setItem(key(), saved)
    expect(() => loadReportEmployees(1, scope)).toThrow()
  })
  it('存储读取和写入错误交给页面处理，不伪装成成功', () => {
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('read blocked') })
    expect(() => loadReportEmployees(1, scope)).toThrow('read blocked')
    get.mockRestore()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('write blocked') })
    expect(() => saveReportEmployees(1, scope, { work: 'employee' })).toThrow('write blocked')
  })
})
