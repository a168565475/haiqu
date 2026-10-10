import { describe, expect, it } from 'vitest'

import {
  QUOTATION_WORKFLOW_STATES,
  quotationWorkflowState,
  transitionQuotationWorkflow,
} from './quotationWorkflow'

describe('报价 F01—F06 状态契约', () => {
  it('完整登记 34 个唯一状态', () => {
    expect(QUOTATION_WORKFLOW_STATES).toHaveLength(34)
    expect(new Set(QUOTATION_WORKFLOW_STATES.map((state) => state.id)).size).toBe(34)
  })

  it.each(['F01', 'F02', 'F03', 'F04', 'F05', 'F06'] as const)('%s 有初始态和可恢复的终态', (flow) => {
    const states = QUOTATION_WORKFLOW_STATES.filter((state) => state.flow === flow)
    expect(states.some((state) => state.phase === 'INITIAL')).toBe(true)
    expect(states.some((state) => ['SUCCESS', 'FAILED', 'CONFLICT', 'EMPTY'].includes(state.phase))).toBe(true)
  })

  it('只允许在同一流程内转换', () => {
    expect(transitionQuotationWorkflow('F03-S01', 'F03-S02').id).toBe('F03-S02')
    expect(() => transitionQuotationWorkflow('F03-S02', 'F04-S03')).toThrow('不能从 F03 直接切换到 F04')
  })

  it('未知状态会显式报错', () => {
    expect(() => quotationWorkflowState('F99-S99' as never)).toThrow('未知报价流程状态')
  })

  it.each(QUOTATION_WORKFLOW_STATES)('$id 可从本流程初始态恢复并显示', (state) => {
    const initial = QUOTATION_WORKFLOW_STATES.find((item) => item.flow === state.flow && item.phase === 'INITIAL')
    expect(initial).toBeTruthy()
    expect(transitionQuotationWorkflow(initial!.id, state.id)).toEqual(state)
    expect(state.title.trim()).not.toBe('')
    expect(state.description.trim()).not.toBe('')
  })
})
