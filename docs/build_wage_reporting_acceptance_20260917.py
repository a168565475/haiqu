from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
prototype = root / 'outputs/work_reporting_prototype_20260917_v1'
sources = json.loads((prototype/'design_sources.json').read_text(encoding='utf-8'))
assert sources['revision'] == 'controls-r2'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
pages = []
routes = {'G01':'/workshop/wage-schemes','G02':'/workshop/wage-schemes/new','G03':'G02/G04 内历史弹窗','G04':'/workshop/wage-schemes/:schemeId/change','G05':'/workshop/wage-schemes/:schemeId','B01':'/workshop/plans/{metalworking,cutting,sewing,assembly}','B02':'/workshop/work-reports/new','B03':'/workshop/work-reports','B04':'/workshop/work-reports/days/:productionDate'}
for entry in sources['pages']:
    capture = prototype/'public/qa'/f"{entry['page']}.png"
    assert sha(capture) == entry['captureSha256'], f"截图与现有清单不一致：{capture}"
    pages.append({'id':entry['page'],'prototypeHashRoute':entry['page'],'proposedApplicationRoute':routes[entry['page']],'referenceScreenshot':str(capture.relative_to(root)).replace('\\','/'),'sha256':sha(capture),'applicationVisualAcceptance':'NOT_RUN'})

cases = [
 ('S01','设计基线','原型源码与九页截图哈希一致，controls-r2 未被替换'),
 ('S02','视觉','1920×1080/DPR1，221项旧原型计数只作参考；正式可见业务控件全部32px、圆角5px'),
 ('S03','视觉','表头44px、普通行40px、表头11px/正文12px、单元格水平内边距16px'),
 ('S04','视觉','展示Tag24px、Strong语义色、分页48px；可编辑状态选择器32px'),
 ('S05','视觉','九页及历史弹窗截图与修正版基准逐页核对，保留并排和差异图'),
 ('S06','视觉','无整页缩放及横向溢出；1440/1202辅助尺寸内部滚动，控件仍32px'),
 ('S07','视觉','弹窗内输入/按钮/表格遵循同一尺寸与字体；拖动、最大化、还原、焦点无异常'),
 ('W01','工价','任务单只能关联自己的产品行，工序候选按厂内车间＋工艺＋品名过滤'),
 ('W02','工价','历史不匹配时禁止引用，不继承源订单、审批和累计数量'),
 ('W03','工价','修改工价任意有效填写不改变申报工价和合计'),
 ('W04','工价','正常申报价直接相加，作废不计；空价不默认为零'),
 ('W05','工价','单位缺失不能送审；裁剪名称整套不意味着以套计价'),
 ('W06','工价','非厂长直接请求批准返回403，待审批内容的ETag防覆盖'),
 ('W07','工价','重复送审/批准及并发变更不产生冲突有效版本'),
 ('W08','工价','同目录工序不同部位和价格，以及已有行改选同工序，按scheme_line_id正确取价'),
 ('W09','工价','调价沿用稳定工作项，累计数量不归零，原报工单价不改变'),
 ('E01','入口','四类计划带入真实排产产品；已有生产领料和主计划入口保留'),
 ('E02','入口','新产品方案批准后计划状态与报工按钮实时变化，禁止硬编码产品ID'),
 ('R01','报工','方案正常明细自动生成平铺行，员工/工序/线别同一行，无嵌套子表'),
 ('R02','报工','新增行仅选当前方案明细，能够区分同名工序的不同部位和价格'),
 ('R03','报工','数量0、负数、NaN及Infinity拒绝；数量大于订单量但合法有效允许保存'),
 ('R04','报工','只记录独立计件；没有共同产量分摊、计时或套数换算入口'),
 ('R05','报工','非本车间/无效员工拒绝；装配必须选1/2/3线，其他车间不强制'),
 ('R06','报工','按生产日期匹配批准版本；老生产日补录不取最新涨价版本'),
 ('R07','报工','生产日期无适用版本阻止保存；日期改变重新取价，不保留失效单价'),
 ('R08','报工','保存前版本变化返回冲突，不静默换价或写入客户端篡改单价'),
 ('R09','报工','整单保存立即生效，没有待审核状态；任一行失败整单回滚'),
 ('R10','报工','同UUID同内容重试一次入账，不同内容冲突；真实第二次报工合法独立保存'),
 ('R11','报工','并发提交不丢明细，后端Decimal计算后逐行到分再汇总'),
 ('R12','报工','成功报工不扣库存、不自动入成品、不标记工资已支付'),
 ('D01','日期查询','按生产日期分页汇总，金额和人数/订单/产品去重口径与真实明细一致'),
 ('D02','日期查询','点击日期看到所有可见报工记录的逐行明细，保留原记录身份和快照'),
 ('D03','日期查询','日期筛选不改已报工总累计，工序各单位数量不混合成成品量'),
 ('D04','日期查询','修改主数据名称或以后批准价格不改变历史快照'),
 ('P01','权限','列表/选项/详情/汇总均检查同一车间权限，无法猜ID跨范围读写'),
 ('P02','权限','登录录入人和车间计件员工分别记录，不按名字匹配账号授权'),
 ('F01','异常','无数据、无方案、请求失败重试、无权限、保存中和冲突反馈真实且保留输入'),
 ('F02','持久化','刷新浏览器仍可查询成功报工；禁止以内存Mock替代API'),
 ('Q01','交付','专项测试、类型检查、构建、迁移检查有最终日志；失败与未跑项明示'),
 ('Q02','交付','真实写入仅在隔离测试库；共享库迁移/正式上线状态另列'),
]
manifest = {
 'version':'1.0','date':'2026-09-17','executionMode':'CONTINUOUS','documentType':'DEVELOPMENT_PLAN_ACCEPTANCE_CHECKLIST',
 'businessConfirmed':{'quantityUpperLimit':None,'quantityRule':'FINITE_DECIMAL_GREATER_THAN_ZERO','priceVersionBasis':'PRODUCTION_DATE','wageSchemeScope':'ONE_SCHEME_LINEAGE_PER_PRODUCT_LINE_AND_WORKSHOP_WITH_MULTIPLE_CRAFTS','versionTransition':'NEW_EFFECTIVE_DATE_CLOSES_PREVIOUS_DAY_SAME_DAY_REPLACEMENT_FORBIDDEN','clothHolePlanMapping':'NOT_CONNECTED_TO_EXISTING_FOUR_PLAN_CATEGORIES','lateReportingTaskStatuses':['READY','IN_PRODUCTION','PAUSED','COMPLETED','CANCELLED'],'workReportCorrection':'DIRECT_EDIT_WITH_ETAG_AND_REPRICE','reportingMode':'INDEPENDENT_EMPLOYEE_PIECEWORK','requiresReportApproval':False,'deductStockOnReport':False},
 'prototype':{'path':str(prototype.relative_to(root)).replace('\\','/'),'revision':'controls-r2','manifestSha256':sha(prototype/'design_sources.json'),'specSha256':sha(root/'DESIGN.md'),'implementationHashes':sources['implementation']},
 'applicationStatus':{'development':'PARTIAL_IMPLEMENTED_BLOCKED_BY_D05','migrations':'ISOLATED_TEST_DATABASE_PASS_SHARED_NOT_RUN','apiAcceptance':'PARTIAL_AUTOMATED_15_PASS_FULL_NOT_RUN','visualAcceptance':'NOT_RUN'},
 'pages':pages,'cases':[{'id':id,'category':category,'expected':expected,'status':'NOT_RUN','evidence':[]} for id,category,expected in cases],
 'remainingDecisions':['D05_HISTORY_DRAFT_DETAILS'],
 'sourceOfTruth':'用户最新业务确认 > DESIGN.md 控件规范 > controls-r2 原型 > 未被覆盖的旧 PRD',
 'passRule':'全部必需正式用例通过、逐页视觉复核完成且关键业务决策关闭；不继承原型 PASS 状态'
}
target=root/'docs/workshop_wage_reporting_acceptance_20260917.json'
target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
assert len(pages)==9 and len(set(c['id'] for c in manifest['cases']))==len(cases)
assert all(c['status']=='NOT_RUN' for c in manifest['cases'])
print(json.dumps({'pages':len(pages),'cases':len(cases),'baseline':'controls-r2','sourceHashChecks':'PASS','formalAcceptance':'NOT_RUN'}))
