import type { DirectorJob, DirectorWorkshop } from '@/types/workshopDirectorWorkbench'

export const workshopName: Record<DirectorWorkshop, string> = { METAL: '金工', SEWING: '车缝', ASSEMBLY: '装配' }
export const deadlineLabel: Record<DirectorWorkshop, string> = { METAL: '要求金工回货日', SEWING: '要求车缝回货日', ASSEMBLY: '要求成品入库日' }
export const stageLabel: Record<DirectorJob['stage'], string> = { working: '在制', planned: '待确认开工', completed: '已完成', unknown: '进度待核实' }
export const shortDate = (date: string) => date.slice(5, 10).replace('-', '/')
const numberFormat = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 8 })
export const amount = (n: string | null, unit = '') => n === null ? '—' : (numberFormat.format(Number(n)) + (unit ? ' ' + unit : ''))
export const countdown = (days: number) => days < 0 ? '已超 ' + Math.abs(days) + ' 天' : days === 0 ? '今天到期' : '还剩 ' + days + ' 天'
export const dueTone = (days: number) => days < 0 ? 'late' : days === 0 ? 'today' : 'clear'
