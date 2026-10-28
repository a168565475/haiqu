import type { useAuthStore } from '@/stores/auth'

export const systemSettings = [
  { key: 'production', name: '生产维护', description: '维护生产基础资料与材料选项' },
  { key: 'email', name: '邮件账户', description: '管理工作邮箱与收发配置' },
  { key: 'inquiry', name: '询盘处理时限', description: '设置询盘各阶段的处理时限' },
  { key: 'masterData', name: '基础资料中心', description: '维护国家、币种、单位等资料' },
  { key: 'numberRules', name: '编号规则', description: '查看业务单据的编号方式' },
  { key: 'notifications', name: '通知规则', description: '配置业务通知与接收范围' },
  { key: 'sendRecords', name: '发送记录', description: '查看企微接收人、内容与发送结果' },
  { key: 'theme', name: '界面主题', description: '选择界面配色与显示风格' },
  { key: 'parameters', name: '业务参数', description: '维护业务参数与配置草稿' },
  { key: 'wecom', name: '企业微信管理', description: '管理企微接入与应用消息' },
  { key: 'access', name: '权限管理', description: '管理角色授权、团队与授权记录' },
  { key: 'dictionary', name: '字典配置', description: '维护分类选项、启停与排序' },
] as const

export type SystemSettingsKey = typeof systemSettings[number]['key']
export type SystemSettingsEntry = typeof systemSettings[number]

const productionModels = [
  'productcategory', 'productionunit', 'productcolor', 'productitem',
  'fabricmaterial', 'fabricspecification', 'fabricwidth',
  'accessoryproductname', 'accessoryspecification', 'accessorycolor', 'accessorymaterial',
  'tubeproductname', 'tubethickness', 'tubediameter', 'tubematerial', 'tubeshape', 'tubecoatingcolor',
]
const masterDataModels = ['country', 'currency', 'exchangerate', 'unit', 'incoterm', 'paymentmethod', 'transportmethod', 'port', 'courier']

export function canOpenSystemSetting(auth: ReturnType<typeof useAuthStore>, key: SystemSettingsKey): boolean {
  if (!auth.isAuthenticated || auth.waitingForRole) return false
  const canView = (models: string[]) => auth.user?.is_superuser === true
    || auth.hasAnyPermission(models.map(model => `reference_data.view_${model}`))
  switch (key) {
    case 'production': return canView(productionModels)
    case 'masterData': return canView(masterDataModels)
    case 'email': return auth.user?.employee != null
    case 'inquiry': return auth.hasPermission('workflow.view_slapolicy')
    case 'numberRules': return canView(['numberrule'])
    case 'notifications': return auth.managementCan('access_control.manage_notifications')
    case 'sendRecords': return auth.managementCan('access_control.manage_notifications') || auth.managementCan('access_control.manage_wecom')
    case 'wecom': return auth.managementCan('access_control.manage_wecom')
    case 'access': return auth.canReadAccessDirectory
    case 'dictionary': return canView(['dictionarytype', 'referencedictionary'])
    case 'parameters': return canView(['systemparameterdefinition'])
    case 'theme': return true
  }
}
