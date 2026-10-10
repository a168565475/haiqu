import { describe, expect, it } from 'vitest'
import type { InquirySla, InquiryWorkCalendar } from '@/types/inquiry'
import { workMilliseconds, handlingStatusLabel, currentHandlingRecords, handlingStageLabel, handlingTargetLabel } from './inquiryWorktime'
import { slaPresentation } from './inquiryDetailState'

const calendar: InquiryWorkCalendar = { mode: 'ALTERNATING_WEEKS_V1', timezone: 'Asia/Shanghai', rest_saturday: '2026-09-05', periods: [[510,720],[810,1050]] }
const at = (value: string) => Date.parse(`${value}+08:00`)
describe('询盘大小周工作时钟', () => {
  it('按各记录的自定义上下班时段累计，拒绝重叠时段', () => {
    const changed = { ...calendar, periods: [[540,720],[840,1080]] } as InquiryWorkCalendar
    expect(workMilliseconds(at('2026-09-14T09:00'), at('2026-09-14T15:00'), changed)).toBe(4*3600000)
    expect(workMilliseconds(at('2026-09-14T12:00'), at('2026-09-14T14:00'), changed)).toBe(0)
    expect(Number.isNaN(workMilliseconds(0,1,{...calendar,periods:[[510,720],[700,1050]]}))).toBe(true)
  })
  it('并行时限优先最近截止，过滤历史并保留输入顺序', () => {
    const records = [
      {id:'first',is_current:true,stage_code:'FIRST_RESPONSE',next_deadline_at:'2026-09-14T14:00:00+08:00'},
      {id:'old',is_current:false,stage_code:'ASSIGNMENT',next_deadline_at:'2026-09-13T09:00:00+08:00'},
      {id:'assign',is_current:true,stage_code:'ASSIGNMENT',next_deadline_at:'2026-09-14T09:00:00+08:00'},
      {id:'missing',is_current:true,next_deadline_at:null},
    ] as InquirySla[]
    expect(currentHandlingRecords(records).map(item=>item.id)).toEqual(['assign','first','missing'])
    expect(records[0]?.id).toBe('first')
    for (const stage of ['ASSIGNMENT','FIRST_RESPONSE','REQUIREMENT_CONFIRMATION','QUOTE_CREATION','QUOTE_DELIVERY','CUSTOMER_FOLLOW_UP','POST_ACCEPTANCE','SAMPLE_FOLLOW_UP']) expect(handlingStageLabel(stage)).not.toBe('处理阶段')
    expect(handlingTargetLabel(450)).toBe('7.5 个工作小时')
    expect(handlingTargetLabel(30)).toBe('30 分钟')
    expect(handlingTargetLabel(NaN)).toBe('未启用')
  })
  it('午休和双休不累计，单休周六累计', () => {
    expect(workMilliseconds(at('2026-09-10T08:30'), at('2026-09-10T14:00'), calendar)).toBe(4*3600000)
    expect(workMilliseconds(at('2026-09-11T16:30'), at('2026-09-12T11:30'), calendar)).toBe(4*3600000)
    expect(workMilliseconds(at('2026-09-18T16:30'), at('2026-09-21T11:30'), calendar)).toBe(4*3600000)
    expect(workMilliseconds(at('2026-09-10T12:00'), at('2026-09-10T13:30'), calendar)).toBe(0)
    expect(workMilliseconds(at('2026-08-29T08:30'), at('2026-08-29T14:00'), calendar)).toBe(4*3600000)
  })
  it('详情在整个午休期间保持剩余30分钟和87.5%进度', () => {
    const record = {status:'RUNNING',started_at:'2026-09-10T08:30:00+08:00',next_deadline_at:'2026-09-10T14:00:00+08:00',work_calendar:calendar} as InquirySla
    for (const instant of ['2026-09-10T12:00','2026-09-10T13:00','2026-09-10T13:30']) {
      expect(slaPresentation(record, at(instant), 'NEW')).toMatchObject({label:'剩余 30 分钟（工作时间）',percentage:87.5,overdue:false})
    }
    expect(slaPresentation({...record,status:'BREACHED',completed_at:'2026-09-10T14:05:00+08:00'},at('2026-09-11T09:00'),'ANALYZING')).toMatchObject({label:'超时完成',percentage:null})
  })
  it('旧记录保持原连续时长，非法日历不会显示虚构时间', () => {
    expect(workMilliseconds(at('2026-09-10T12:00'),at('2026-09-10T13:30'))).toBe(90*60000)
    expect(Number.isNaN(workMilliseconds(NaN,Date.now(),calendar))).toBe(true)
    expect(Number.isNaN(workMilliseconds(0,1,{...calendar,rest_saturday:'bad'}))).toBe(true)
    expect(handlingStatusLabel('MET')).toBe('按时完成')
    expect(handlingStatusLabel('RUNNING',null,'2026-09-10T14:00:00+08:00',at('2026-09-10T14:01'))).toBe('已超时')
  })
})
