import { ref } from 'vue'

export type QuotationFlowCode = 'F01' | 'F02' | 'F03' | 'F04' | 'F05' | 'F06'
export type QuotationFlowPhase = 'INITIAL' | 'PROCESSING' | 'SUCCESS' | 'FAILED' | 'CONFLICT' | 'RECOVERY' | 'EMPTY'

export interface QuotationWorkflowStateDefinition {
  id: string
  flow: QuotationFlowCode
  phase: QuotationFlowPhase
  title: string
  description: string
}

export const QUOTATION_WORKFLOW_STATES = [
  { id: 'F01-S01', flow: 'F01', phase: 'INITIAL', title: '锁定并签发', description: '核对联系人、地址和报价条款后开始。' },
  { id: 'F01-S02', flow: 'F01', phase: 'PROCESSING', title: '正在锁定报价', description: '正在冻结报价快照，请勿重复提交。' },
  { id: 'F01-S03', flow: 'F01', phase: 'PROCESSING', title: '正在签发报价', description: '锁定已完成，正在使用最新版本签发。' },
  { id: 'F01-S04', flow: 'F01', phase: 'SUCCESS', title: '报价已签发', description: '可以生成或上传正式报价文件。' },
  { id: 'F01-S05', flow: 'F01', phase: 'FAILED', title: '签发未完成', description: '版本保持已锁定；重试时只会重新签发。' },
  { id: 'F02-S01', flow: 'F02', phase: 'PROCESSING', title: '正在生成正式 PDF', description: '正式文件生成中，请勿重复提交。' },
  { id: 'F02-S02', flow: 'F02', phase: 'SUCCESS', title: '正式 PDF 已生成', description: '正式文件已登记，可以下载或准备发送。' },
  { id: 'F02-S03', flow: 'F02', phase: 'INITIAL', title: '选择已有文件上传', description: '请选择不超过 10MB 的真实 PDF 或 XLSX 文件。' },
  { id: 'F02-S04', flow: 'F02', phase: 'PROCESSING', title: '正在校验上传文件', description: '正在检查格式、大小、真实文件签名和病毒扫描结果。' },
  { id: 'F02-S05', flow: 'F02', phase: 'SUCCESS', title: '上传成功并登记', description: '当前正式附件已更新，历史文件仍保留。' },
  { id: 'F02-S06', flow: 'F02', phase: 'FAILED', title: '上传文件不合格', description: '请上传不超过 10MB 的真实 PDF 或 XLSX 文件。' },
  { id: 'F02-S07', flow: 'F02', phase: 'PROCESSING', title: '正在重新生成正式 PDF', description: '旧正式文件在新文件登记成功前仍可查看。' },
  { id: 'F02-S08', flow: 'F02', phase: 'SUCCESS', title: '下载已开始', description: '浏览器已接收下载响应，请在浏览器下载列表查看。' },
  { id: 'F03-S01', flow: 'F03', phase: 'INITIAL', title: '邮件发送', description: '填写当前收件人、主题、正文和价格口径。' },
  { id: 'F03-S02', flow: 'F03', phase: 'INITIAL', title: '编辑邮件正文', description: '确认正文只更新当前发送表单，不会立即发信。' },
  { id: 'F03-S03', flow: 'F03', phase: 'SUCCESS', title: '邮件正文已确认', description: '已返回发送资料，可继续核对附件与收件人。' },
  { id: 'F03-S04', flow: 'F03', phase: 'PROCESSING', title: '邮件发送处理中', description: '发送请求已持久化，请勿重复提交。' },
  { id: 'F03-S05', flow: 'F03', phase: 'SUCCESS', title: '投递已被接受', description: '系统已登记一条正式邮件发送记录。' },
  { id: 'F03-S06', flow: 'F03', phase: 'RECOVERY', title: '再次发送确认', description: '再次发送会创建新的尝试和发送记录。' },
  { id: 'F03-S07', flow: 'F03', phase: 'RECOVERY', title: '发送失败与恢复', description: '表单内容已保留；结果不确定时请核对发件箱后处理。' },
  { id: 'F04-S01', flow: 'F04', phase: 'INITIAL', title: '人工发送登记', description: '仅登记系统外发送行为，不调用邮件服务。' },
  { id: 'F04-S02', flow: 'F04', phase: 'PROCESSING', title: '正在登记人工发送', description: '正在保存发送对象、价格口径和证据。' },
  { id: 'F04-S03', flow: 'F04', phase: 'SUCCESS', title: '人工发送已登记', description: '系统已新增一条人工发送记录。' },
  { id: 'F04-S04', flow: 'F04', phase: 'FAILED', title: '人工发送登记失败', description: '表单内容已保留；请补充证据说明或外部凭证号。' },
  { id: 'F05-S01', flow: 'F05', phase: 'INITIAL', title: '记录客户接受', description: '仅可选择真实已发送版本及对应价格口径。' },
  { id: 'F05-S02', flow: 'F05', phase: 'PROCESSING', title: '正在记录接受结果', description: '提交期间不会创建样品或销售订单。' },
  { id: 'F05-S03', flow: 'F05', phase: 'SUCCESS', title: '客户接受已记录', description: '可以按需进入创建样品或创建销售订单。' },
  { id: 'F05-S04', flow: 'F05', phase: 'FAILED', title: '接受结果未保存', description: '服务端报价结果未改变，请核对后重试。' },
  { id: 'F06-S01', flow: 'F06', phase: 'INITIAL', title: '版本与差异', description: '选择比较基准和目标版本查看真实差异。' },
  { id: 'F06-S02', flow: 'F06', phase: 'INITIAL', title: '选择比较版本', description: '选择比较基准与目标版本，读取真实差异。' },
  { id: 'F06-S03', flow: 'F06', phase: 'PROCESSING', title: '正在创建版本副本', description: '新版本将保留所选来源版本。' },
  { id: 'F06-S04', flow: 'F06', phase: 'SUCCESS', title: '副本创建完成', description: '新草稿已创建，可以进入编辑。' },
  { id: 'F06-S05', flow: 'F06', phase: 'CONFLICT', title: '版本已经变化', description: '请重新加载版本树后再创建副本。' },
  { id: 'F06-S06', flow: 'F06', phase: 'EMPTY', title: '只有一个版本', description: '暂无可比较版本，但仍可基于当前版本创建副本。' },
] as const satisfies readonly QuotationWorkflowStateDefinition[]

export type QuotationWorkflowStateId = typeof QUOTATION_WORKFLOW_STATES[number]['id']

const stateById = new Map<string, QuotationWorkflowStateDefinition>(
  QUOTATION_WORKFLOW_STATES.map((state) => [state.id, state]),
)

export function quotationWorkflowState(id: QuotationWorkflowStateId): QuotationWorkflowStateDefinition {
  const state = stateById.get(id)
  if (!state) throw new Error(`未知报价流程状态：${id}`)
  return state
}

export function transitionQuotationWorkflow(
  currentId: QuotationWorkflowStateId,
  nextId: QuotationWorkflowStateId,
): QuotationWorkflowStateDefinition {
  const current = quotationWorkflowState(currentId)
  const next = quotationWorkflowState(nextId)
  if (current.flow !== next.flow) throw new Error(`不能从 ${current.flow} 直接切换到 ${next.flow}`)
  return next
}

export function useQuotationWorkflow(initialId: QuotationWorkflowStateId) {
  const current = ref<QuotationWorkflowStateDefinition>(quotationWorkflowState(initialId))
  const setState = (nextId: QuotationWorkflowStateId) => {
    current.value = transitionQuotationWorkflow(current.value.id as QuotationWorkflowStateId, nextId)
  }
  const reset = (nextId: QuotationWorkflowStateId) => {
    current.value = quotationWorkflowState(nextId)
  }
  return { current, setState, reset }
}
