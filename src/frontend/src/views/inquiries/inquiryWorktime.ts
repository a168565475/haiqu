import type { InquirySla, InquiryWorkCalendar } from '@/types/inquiry'

// 日历来自后端阶段快照；旧记录没有快照时保留连续计时。
export function workMilliseconds(start: number, end: number, calendar?: InquiryWorkCalendar | null): number {
  if (!Number.isFinite(start) || !Number.isFinite(end)) return NaN
  if (!calendar) return end - start
  if (calendar.mode !== 'ALTERNATING_WEEKS_V1' || calendar.timezone !== 'Asia/Shanghai') return NaN
  if (end < start) return -workMilliseconds(end, start, calendar)
  const dayLength = 86400000
  const offset = 8 * 3600000
  const anchor = Date.parse(`${calendar.rest_saturday}T00:00:00+08:00`)
  if (!Number.isFinite(anchor) || new Date(anchor + offset).getUTCDay() !== 6) return NaN
  if (!validWorkPeriods(calendar.periods)) return NaN
  const first = Math.floor((start + offset) / dayLength) * dayLength - offset
  const last = Math.floor((end + offset) / dayLength) * dayLength - offset
  if ((last - first) / dayLength > 36600) return NaN
  let total = 0
  for (let day = first; day <= last; day += dayLength) {
    const weekday = new Date(day + offset).getUTCDay()
    if (weekday === 0 || (weekday === 6 && Math.floor((day - anchor) / (7 * dayLength)) % 2 === 0)) continue
    for (const [begin, finish] of calendar.periods) {
      total += Math.max(0, Math.min(end, day + finish * 60000) - Math.max(start, day + begin * 60000))
    }
  }
  return total
}

export function handlingStageLabel(stage: string) {
  return ({ ASSIGNMENT:'分配负责人', FIRST_RESPONSE: '首次回复', REQUIREMENT_CONFIRMATION: '需求确认', QUOTE_CREATION:'创建报价', QUOTE_DELIVERY:'完成并发送报价', CUSTOMER_FOLLOW_UP:'报价后跟进', POST_ACCEPTANCE:'报价接受后推进', SAMPLE_FOLLOW_UP:'样品进度跟进' } as Record<string, string>)[stage] || '处理阶段'
}

function validWorkPeriods(periods: unknown): periods is [number, number][] {
  if (!Array.isArray(periods) || periods.length!==2) return false
  let previousEnd=-1
  for(const period of periods){
    if(!Array.isArray(period)||period.length!==2||!period.every(Number.isInteger))return false
    const [start,end]=period
    if(start<0||start>=end||end>1440||start<previousEnd)return false
    previousEnd=end
  }
  return true
}

export function workCalendarDescription(calendar: InquiryWorkCalendar) {
  if(!validWorkPeriods(calendar.periods))return '工作日历不完整'
  const clock=(value:number)=>`${String(Math.floor(value/60)).padStart(2,'0')}:${String(value%60).padStart(2,'0')}`
  const periods=calendar.periods.map(([start,end])=>`${clock(start)}—${clock(end)}`).join('、')
  const hours=calendar.periods.reduce((total,[start,end])=>total+end-start,0)/60
  return `工作时段：${periods}，每天 ${Number(hours.toFixed(2))} 小时。`
}

export function currentHandlingRecords(records: InquirySla[]) {
  return records.filter(record=>record.is_current).sort((left,right)=>{
    const leftTime=Date.parse(left.next_deadline_at||''),rightTime=Date.parse(right.next_deadline_at||'')
    return (Number.isFinite(leftTime)?leftTime:Infinity)-(Number.isFinite(rightTime)?rightTime:Infinity) || left.id.localeCompare(right.id)
  })
}

export function handlingTargetLabel(minutes: number) {
  if (!Number.isFinite(minutes)||minutes<=0) return '未启用'
  return minutes<60?`${minutes} 分钟`:`${minutes/60} 个工作小时`
}

export function handlingStatusLabel(status: string, completedAt?: string | null, deadline?: string | null, now = Date.now()) {
  if (status === 'RUNNING' && deadline && Date.parse(deadline) < now && !completedAt) return '已超时'
  if (status === 'BREACHED') return completedAt ? '超时完成' : '已超时'
  return ({ RUNNING: '进行中', MET: '按时完成', COMPLETED: '已完成', CANCELLED: '已终止', PAUSED: '已暂停' } as Record<string, string>)[status] || '未知状态'
}
