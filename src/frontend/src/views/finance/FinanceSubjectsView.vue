<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance } from 'element-plus'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import SubjectTable from './SubjectTable.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchFinanceSubjects, fetchFinanceSubject, fetchSubjectTree, createFinanceSubject, updateFinanceSubject, deleteFinanceSubject } from '@/api/financeSubjects'
import type { FinanceSubject, FinanceSubjectInput, FinanceSubjectQuery } from '@/types/financeSubjects'

const auth = useAuthStore()
const can = (action: string) => auth.user?.is_superuser === true || auth.hasPermission(`finance.${action}_accountingsubject`)
const rows = ref<FinanceSubject[]>([]), total = ref(0), page = ref(1)
const search = ref(''), status = ref<'' | 'ACTIVE' | 'INACTIVE'>(''), level = ref<number | ''>(3)
const applied = reactive({ q: '', status: '' as '' | 'ACTIVE' | 'INACTIVE', level: 3 as number | '' })
const loading = ref(false), loaded = ref(false), forbidden = ref(false), listError = ref('')
let listRequest = 0, detailRequest = 0, treeRequest = 0, rootRequest = 0, parentRequest = 0
let listController: AbortController | undefined, detailController: AbortController | undefined, treeController: AbortController | undefined
let disposed = false
const busy = ref(false), dialog = ref(false), mode = ref<'create' | 'edit' | 'detail'>('create')
const record = ref<FinanceSubject>(), latest = ref<FinanceSubject>(), detailLoading = ref(false)
const formRef = ref<FormInstance>()
const blank = (): FinanceSubjectInput => ({ parent_id: null, level: 3, name: '', status: 'ACTIVE' })
const form = reactive(blank()), rootId = ref(''), original = ref('')
const fingerprint = () => JSON.stringify({ ...form, rootId: rootId.value })
const dirty = computed(() => dialog.value && mode.value !== 'detail' && fingerprint() !== original.value)
const submitting = ref(false), uncertain = ref(false), formError = ref(''), conflict = ref(false)
const fieldErrors = ref<Record<string, string>>({})
let creationKey = '', submittedBody: FinanceSubjectInput | undefined
const roots = ref<FinanceSubject[]>([]), parents = ref<FinanceSubject[]>([])
const rootPage = ref(1), parentPage = ref(1), rootTotal = ref(0), parentTotal = ref(0)
const optionLoading = reactive({ root: false, parent: false }), optionError = ref('')
const treeOpen = ref(false), treeRows = ref<FinanceSubject[]>([]), treePage = ref(1), treeTotal = ref(0)
const treeLoading = ref(false), treeError = ref(''), branch = ref<FinanceSubject[]>([])
const labels = ['费用类型', '一级科目', '二级科目']
const title = computed(() => mode.value === 'detail' ? '会计科目详情' : mode.value === 'edit' ? '编辑会计科目' : '新增会计科目')
const pathPreview = computed(() => {
  if (mode.value !== 'create' && record.value) return [...record.value.path_names.slice(0,-1), form.name || '待填写名称'].join(' / ')
  const root = roots.value.find(item=>item.id===rootId.value)?.name
  const parent = parents.value.find(item=>item.id===form.parent_id)?.name
  return [...(form.level>1?[root || '待选费用类型']:[]), ...(form.level===3?[parent || '待选一级科目']:[]), form.name || '待填写名称'].join(' / ')
})
function message(error: unknown) {
  if (axios.isAxiosError(error)) return error.response?.data?.error?.message || '请求未完成，请检查网络后重试。'
  return error instanceof Error ? error.message : '请求失败，请重试。'
}
async function loadList() {
  if (!can('view')) return
  const request = ++listRequest
  listController?.abort(); listController = new AbortController()
  loading.value = true; listError.value = ''
  const query: FinanceSubjectQuery = { page: page.value, page_size: 20, q: applied.q,
    ...(applied.status?{status:applied.status}:{}), ...(applied.level?{level:applied.level}:{}) }
  try {
    const result = await fetchFinanceSubjects(query, listController.signal)
    if (request!==listRequest || disposed) return
    rows.value=result.data; total.value=result.meta.total; page.value=result.meta.page; loaded.value=true; forbidden.value=false
  } catch(error) {
    if (request!==listRequest || disposed || axios.isCancel(error)) return
    if (axios.isAxiosError(error) && [401,403].includes(error.response?.status || 0)) { forbidden.value=true; rows.value=[]; total.value=0 }
    listError.value=`${loaded.value && !forbidden.value?'刷新失败，保留上次结果。':''}${message(error)}`
  } finally { if (request===listRequest && !disposed) loading.value=false }
}
function filter(reset=false) {
  if (reset) { search.value=''; status.value=''; level.value=3 }
  Object.assign(applied,{q:search.value.trim(),status:status.value,level:level.value}); page.value=1; void loadList()
}
async function loadTree() {
  const request=++treeRequest
  treeController?.abort(); treeController=new AbortController(); treeLoading.value=true; treeError.value=''
  try {
    const result=await fetchSubjectTree({page:treePage.value,page_size:20,...(branch.value.length?{parent_id:branch.value.at(-1)!.id}:{})},treeController.signal)
    if (request!==treeRequest || disposed) return
    treeRows.value=result.data; treeTotal.value=result.meta.total
  } catch(error) { if (request===treeRequest && !axios.isCancel(error)) treeError.value=message(error) }
  finally { if(request===treeRequest && !disposed) treeLoading.value=false }
}
function openTree() { branch.value=[]; treePage.value=1; treeRows.value=[]; treeOpen.value=true; void loadTree() }
function navigateTree(index: number) { branch.value=branch.value.slice(0,index); treePage.value=1; treeRows.value=[]; void loadTree() }
async function loadOptions(kind: 'root' | 'parent', more=false) {
  const request=kind==='root'?++rootRequest:++parentRequest
  const targetPage=kind==='root'?rootPage:parentPage
  if (!more) targetPage.value=1
  const requestedPage=more?targetPage.value+1:1
  const selectedRoot=rootId.value
  optionLoading[kind]=true; optionError.value=''
  try {
    const result=await fetchSubjectTree({page:requestedPage,page_size:20,...(kind==='parent'?{parent_id:selectedRoot}:{})})
    if (disposed || !dialog.value || request!==(kind==='root'?rootRequest:parentRequest) || (kind==='parent' && rootId.value!==selectedRoot)) return
    const target=kind==='root'?roots:parents
    target.value=more?[...target.value,...result.data]:result.data
    targetPage.value=requestedPage
    if(kind==='root') rootTotal.value=result.meta.total; else parentTotal.value=result.meta.total
  } catch(error) { if (!disposed && request===(kind==='root'?rootRequest:parentRequest)) optionError.value=message(error) }
  finally { if(request===(kind==='root'?rootRequest:parentRequest)) optionLoading[kind]=false }
}
function changeLevel() { rootId.value=''; form.parent_id=null; parents.value=[]; ++parentRequest }
function changeRoot() { form.parent_id=form.level===2?rootId.value:null; parents.value=[]; ++parentRequest; if(form.level===3 && rootId.value) void loadOptions('parent') }
async function openEditor(action: 'create' | 'edit' | 'detail', row?: FinanceSubject) {
  if (!can(action==='create'?'add':action==='edit'?'change':'view')) return
  mode.value=action; record.value=undefined; latest.value=undefined; detailLoading.value=false
  formError.value=''; fieldErrors.value={}; conflict.value=false; uncertain.value=false; optionError.value=''
  submittedBody=undefined; creationKey=crypto.randomUUID(); rootId.value=''; roots.value=[]; parents.value=[]
  ++rootRequest; ++parentRequest; Object.assign(form,blank()); original.value=fingerprint(); dialog.value=true
  const request=++detailRequest
  detailController?.abort(); detailController=new AbortController()
  if(action==='create') void loadOptions('root')
  if(!row) return
  detailLoading.value=true
  try {
    const result=await fetchFinanceSubject(row.id,detailController.signal)
    if(request!==detailRequest || !dialog.value || disposed) return
    record.value=result; Object.assign(form,{parent_id:result.parent_id,level:result.level,name:result.name,status:result.status}); original.value=fingerprint()
  } catch(error) { if(request===detailRequest && !axios.isCancel(error)) formError.value=message(error) }
  finally { if(request===detailRequest && !disposed) detailLoading.value=false }
}
async function confirmLeave() {
  if(submitting.value || uncertain.value) { ElMessage.warning(uncertain.value?'提交结果尚未确认，请先重试原提交。':'正在提交，请稍候。'); return false }
  if(!dirty.value) return true
  try { await ElMessageBox.confirm('有未保存的科目信息，确定放弃修改？','离开未保存表单',{confirmButtonText:'放弃修改',cancelButtonText:'继续填写',customClass:'finance-subject-confirm'}); return true } catch { return false }
}
async function closeDialog(done?:()=>void) {
  if(!await confirmLeave()) return
  ++detailRequest; ++rootRequest; ++parentRequest; detailController?.abort(); detailLoading.value=false
  if(done) done(); else dialog.value=false
}
async function refreshAfterMutation() {
  await loadList()
  if(treeOpen.value) {
    // 父改名/启停后重新读取导航路径，避免树标题和完整路径列表不同步。
    const refreshed: FinanceSubject[]=[]
    try { for(const node of branch.value) refreshed.push(await fetchFinanceSubject(node.id)); branch.value=refreshed }
    catch(error) {
      if(axios.isAxiosError(error) && error.response?.status===404) { branch.value=[]; treePage.value=1 }
      else { treeError.value=message(error); return }
    }
    await loadTree()
  }
}
async function confirmImpact(current: FinanceSubject, name: string, nextStatus: string) {
  const notes=[]
  if(name!==current.name) notes.push(`当前路径将从“${current.full_path}”变为“${[...current.path_names.slice(0,-1),name].join(' / ')}”，影响 ${current.affected_path_count} 条完整路径。`)
  if(nextStatus!==current.status) notes.push(`${nextStatus==='INACTIVE'?'停用':'启用'}影响 ${current.affected_path_count} 条完整路径；下级自身状态保持不变。`)
  if(!notes.length) return true
  try { await ElMessageBox.confirm(notes.join(' '),'确认科目变更',{confirmButtonText:'确认',cancelButtonText:'继续编辑',type:'warning',customClass:'finance-subject-confirm'}); return true } catch { return false }
}
async function save() {
  if(submitting.value || detailLoading.value || (mode.value==='edit' && !record.value) || !can(mode.value==='create'?'add':'change')) return
  if(!uncertain.value && !await formRef.value?.validate().catch(()=>false)) return
  if(submitting.value) return
  submitting.value=true
  try {
    if(!uncertain.value && mode.value==='edit' && !await confirmImpact(record.value!,form.name.trim(),form.status)) return
    formError.value=''; fieldErrors.value={}; conflict.value=false
    if(!uncertain.value) submittedBody={...form}
    if(mode.value==='create') await createFinanceSubject(submittedBody!,creationKey)
    else await updateFinanceSubject(record.value!.id,{name:submittedBody!.name,status:submittedBody!.status},record.value!.etag)
    uncertain.value=false; original.value=fingerprint(); dialog.value=false; ElMessage.success('科目保存成功'); await refreshAfterMutation()
  } catch(error) {
    formError.value=message(error)
    const httpStatus=axios.isAxiosError(error)?error.response?.status:undefined
    uncertain.value=mode.value==='create' && (!httpStatus || httpStatus>=500)
    if(!uncertain.value) creationKey=crypto.randomUUID()
    conflict.value=httpStatus===409 || httpStatus===412
    if(axios.isAxiosError(error)) fieldErrors.value=Object.fromEntries(Object.entries(error.response?.data?.error?.field_errors || {}).map(([key,value])=>[key,Array.isArray(value)?value.join('；'):String(value)]))
  } finally { submitting.value=false }
}
async function compareLatest() {
  if(!record.value) return
  const request=detailRequest
  try { const result=await fetchFinanceSubject(record.value.id); if(request===detailRequest && dialog.value && !disposed) latest.value=result }
  catch(error) { if(request===detailRequest && dialog.value) formError.value=message(error) }
}
function acceptLatest() {
  if(!latest.value) return
  record.value=latest.value; latest.value=undefined; conflict.value=false
  formError.value='已确认最新版本；当前名称和状态输入保留，请核对后保存。'
}
async function mutateRow(action: string,row: FinanceSubject) {
  if(busy.value || !can(action==='delete'?'delete':'change')) return
  if(action==='delete' && !row.can_delete) { ElMessage.warning(row.delete_block_reason || '不可删除'); return }
  busy.value=true
  try {
    if(action==='toggle') {
      if(!await confirmImpact(row,row.name,row.status==='ACTIVE'?'INACTIVE':'ACTIVE')) return
      await updateFinanceSubject(row.id,{status:row.status==='ACTIVE'?'INACTIVE':'ACTIVE'},row.etag)
    } else {
      try { await ElMessageBox.confirm(`删除未引用叶科目“${row.full_path}”？`,'删除会计科目',{confirmButtonText:'确认',cancelButtonText:'取消',type:'warning',customClass:'finance-subject-confirm'}) } catch { return }
      await deleteFinanceSubject(row.id,row.etag)
      if(rows.value.length===1 && page.value>1) page.value--
      if(treeRows.value.length===1 && treePage.value>1) treePage.value--
    }
    ElMessage.success(action==='delete'?'科目已删除':'科目状态已更新'); await refreshAfterMutation()
  } catch(error) { listError.value=`${message(error)} 请刷新核对。`; treeError.value=listError.value }
  finally { busy.value=false }
}
function action(name:string,row:FinanceSubject) {
  if(name==='expand') { branch.value.push(row); treePage.value=1; treeRows.value=[]; void loadTree() }
  else if(name==='detail' || name==='edit') void openEditor(name,row)
  else void mutateRow(name,row)
}
function beforeUnload(event:BeforeUnloadEvent) { if(dirty.value || submitting.value || uncertain.value) {event.preventDefault();event.returnValue=''} }
onBeforeRouteLeave(confirmLeave)
onMounted(()=>{void loadList();window.addEventListener('beforeunload',beforeUnload)})
onBeforeUnmount(()=>{disposed=true;++listRequest;++detailRequest;++treeRequest;++rootRequest;++parentRequest;listController?.abort();detailController?.abort();treeController?.abort();window.removeEventListener('beforeunload',beforeUnload)})
</script>

<template>
  <section class="finance-subjects erp-glass-list">
    <el-alert v-if="!can('view') || forbidden" title="没有会计科目查看权限，请联系授权管理员。" type="warning" :closable="false"/>
    <template v-else>
      <div class="erp-list-filter">
        <div class="erp-list-heading"><div class="erp-list-title-row"><h1>会计科目</h1><span class="erp-list-count">{{loaded?`${total} 条科目`:'尚未加载'}}</span></div></div>
        <div class="erp-list-filters">
          <label>搜索 <el-input v-model="search" placeholder="完整路径 / 科目名称" clearable @keyup.enter="filter()"/></label>
          <label>层级 <el-select v-model="level" aria-label="筛选层级"><el-option label="全部层级" value=""/><el-option v-for="(label,index) in labels" :key="label" :label="label" :value="index+1"/></el-select></label>
          <label>自身状态 <el-select v-model="status" aria-label="筛选状态"><el-option label="全部状态" value=""/><el-option label="启用" value="ACTIVE"/><el-option label="停用" value="INACTIVE"/></el-select></label>
          <div class="erp-list-filter-actions"><el-button @click="filter(true)">重置</el-button><el-button @click="filter()">应用筛选</el-button><el-divider direction="vertical"/><el-button v-if="can('add')" type="primary" @click="openEditor('create')">新增科目</el-button></div>
        </div>
      </div>
      <div class="erp-list-data">
        <div class="erp-list-toolbar"><span>费用类型 → 一级科目 → 二级科目；同名科目按完整路径区分</span><el-button @click="openTree">维护上级分类</el-button><el-button :loading="loading" @click="loadList">刷新</el-button></div>
        <el-alert v-if="listError" :title="listError" type="error" :closable="false"><el-button link @click="loadList">重试</el-button></el-alert>
        <div v-loading="loading" class="erp-list-table-frame" :aria-busy="loading"><SubjectTable :rows="rows" :busy="busy" :can-change="can('change')" :can-delete="can('delete')" @action="action">
          <template #empty><span v-if="loading">正在加载科目…</span><span v-else-if="listError">科目数据尚未成功加载</span><div v-else-if="applied.q || applied.status">没有匹配科目 <el-button link @click="filter(true)">清除筛选</el-button></div><div v-else>暂无{{applied.level?labels[Number(applied.level)-1]:'科目'}} <el-button v-if="can('add')" link @click="openEditor('create')">新增科目</el-button></div></template>
        </SubjectTable></div>
        <div class="erp-list-footer"><span>自身状态与上级影响分别显示</span><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="loadList"/></div>
      </div>
    </template>
  </section>
  <AppWindowDialog v-model="treeOpen" title="上级科目维护" :width="860" :min-width="280" :minimizable="false" destroy-on-close modal-class="finance-subject-overlay">
    <div class="subject-tree erp-glass-list">
      <p>按层展开，仅显示当前上级的直接子项；主列表筛选保持不变。</p>
      <nav class="tree-breadcrumb" aria-label="科目树路径"><el-button link @click="navigateTree(0)">全部费用类型</el-button><template v-for="(node,index) in branch" :key="node.id"><span>/</span><el-button link @click="navigateTree(index+1)">{{node.name}}</el-button></template><el-button :loading="treeLoading" @click="loadTree">刷新分类</el-button></nav>
      <el-alert v-if="treeError" :title="treeError" type="error" :closable="false"/>
      <div v-loading="treeLoading" class="erp-list-table-frame tree-frame" :aria-busy="treeLoading"><SubjectTable :rows="treeRows" :busy="busy" :can-change="can('change')" :can-delete="can('delete')" tree @action="action"/></div>
      <el-pagination v-model:current-page="treePage" :page-size="20" :total="treeTotal" layout="prev, pager, next" @current-change="loadTree"/>
    </div>
    <template #footer><el-button @click="treeOpen=false">关闭</el-button></template>
  </AppWindowDialog>
  <AppWindowDialog v-model="dialog" :title="title" :width="680" :min-width="280" :before-close="closeDialog" :minimizable="false" destroy-on-close modal-class="finance-subject-overlay">
    <div v-loading="detailLoading" class="finance-subject-dialog">
      <el-alert v-if="formError" :title="formError" type="error" :closable="false" show-icon/>
      <el-alert v-if="uncertain" title="提交结果尚未确认，输入已保留。请重试原提交，不会重复创建。" type="warning" :closable="false"/>
      <template v-if="mode==='detail' && record">
        <div class="document-heading"><div><h2>{{record.name}}</h2><p>会计科目 · {{labels[record.level-1]}}</p></div><el-tag :type="record.effective_status==='ACTIVE'?'success':'info'">{{record.effective_status==='ACTIVE'?'有效启用':'有效停用'}}</el-tag></div>
        <dl class="document-facts"><div><dt>费用类型</dt><dd>{{record.path_names[0]}}</dd></div><div><dt>一级科目</dt><dd>{{record.path_names[1] || '—'}}</dd></div><div><dt>自身状态</dt><dd>{{record.status==='ACTIVE'?'启用':'停用'}}</dd></div><div><dt>下级 / 完整路径数</dt><dd>{{record.child_count}} / {{record.affected_path_count}}</dd></div><div class="wide"><dt>完整路径</dt><dd>{{record.full_path}}</dd></div></dl>
        <p class="document-note">{{record.blocked_by_ancestor || '完整路径区分同名科目；父级停用时，下级不能用于新业务。'}}</p>
      </template>
      <template v-else-if="mode!=='detail' && (mode==='create' || record)">
        <el-form ref="formRef" :model="form" label-position="top" class="form-grid" :disabled="submitting || uncertain" @submit.prevent="save">
          <el-form-item label="维护层级"><el-select v-model="form.level" aria-label="科目层级" :disabled="mode==='edit'" popper-class="finance-subject-popper" @change="changeLevel"><el-option v-for="(label,index) in labels" :key="label" :label="label" :value="index+1"/></el-select></el-form-item>
          <el-form-item v-if="form.level>1" label="费用类型" :prop="form.level===2?'parent_id':undefined" :rules="form.level===2?[{required:true,message:'请选择费用类型',trigger:'change'}]:[]" required>
            <el-input v-if="mode==='edit'" :model-value="record?.path_names[0]" readonly/>
            <el-select v-else v-model="rootId" aria-label="科目费用类型" :loading="optionLoading.root" popper-class="finance-subject-popper" @change="changeRoot"><el-option v-for="node in roots" :key="node.id" :value="node.id" :label="node.name + (node.effective_status==='INACTIVE'?'（停用）':'')" :disabled="node.effective_status==='INACTIVE'"/><template #footer><el-button v-if="roots.length<rootTotal" :loading="optionLoading.root" @click="loadOptions('root',true)">加载更多费用类型</el-button></template></el-select>
          </el-form-item>
          <el-form-item v-if="form.level===3" label="一级科目" prop="parent_id" :rules="[{required:true,message:'请选择一级科目',trigger:'change'}]" :error="fieldErrors.parent_id">
            <el-input v-if="mode==='edit'" :model-value="record?.path_names[1]" readonly/>
            <el-select v-else v-model="form.parent_id" aria-label="科目一级分类" :disabled="!rootId" :loading="optionLoading.parent" popper-class="finance-subject-popper"><el-option v-for="node in parents" :key="node.id" :value="node.id" :label="node.name + (node.effective_status==='INACTIVE'?'（停用）':'')" :disabled="node.effective_status==='INACTIVE'"/><template #footer><el-button v-if="parents.length<parentTotal" :loading="optionLoading.parent" @click="loadOptions('parent',true)">加载更多一级科目</el-button></template></el-select>
          </el-form-item>
          <el-form-item label="科目名称" prop="name" :rules="[{required:true,whitespace:true,message:'请填写科目名称',trigger:'blur'}]" :error="fieldErrors.name"><el-input v-model="form.name" maxlength="100"/></el-form-item>
          <el-form-item label="自身状态" :error="fieldErrors.status"><el-radio-group v-model="form.status"><el-radio value="ACTIVE">启用</el-radio><el-radio value="INACTIVE">停用</el-radio></el-radio-group></el-form-item>
        </el-form>
        <el-alert v-if="optionError" :title="optionError" type="error" :closable="false"><el-button link @click="loadOptions('root');rootId && loadOptions('parent')">重试选项</el-button></el-alert>
        <p class="path-display">完整路径：{{pathPreview}}</p>
        <el-alert title="父级停用后下级不可用于新业务；恢复父级不改变子项自身启停。已有层级不移动，有下级或引用时不可删除。" type="info" :closable="false"/>
        <el-button v-if="conflict && record" @click="compareLatest">查看最新版本并比较</el-button>
        <div v-if="latest" class="latest-version"><strong>服务器最新版本（当前输入保留）</strong><p>{{latest.full_path}} · {{latest.status==='ACTIVE'?'启用':'停用'}} · {{latest.affected_path_count}} 条完整路径</p><el-button @click="acceptLatest">已比较，保留当前输入继续修改</el-button></div>
      </template>
    </div>
    <template #footer><el-button :disabled="submitting || uncertain" @click="closeDialog()">{{mode==='detail'?'关闭':'取消'}}</el-button><el-button v-if="mode!=='detail'" type="primary" :loading="submitting" :disabled="detailLoading || (mode==='edit' && !record)" @click="save">{{uncertain?'重试原提交':'保存科目'}}</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.finance-subjects .erp-list-filters label:first-child .el-input { width: 230px; }
.finance-subjects .erp-list-filters .el-select { width: 130px; }
.finance-subjects .erp-list-filters > label { white-space: nowrap; }
.erp-list-toolbar { color: var(--erp-color-text-secondary); }
.erp-list-toolbar > .el-button:first-of-type { margin-left: auto; }
.finance-subjects :deep(.el-table__header .cell), .subject-tree :deep(.el-table__header .cell) { font-weight: 500; }
.finance-subject-dialog { display: grid; gap: 16px; color: var(--erp-color-text-primary); }
.form-grid, .document-facts { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px 20px; }
.form-grid .el-form-item { margin-bottom: 0; min-width: 0; }
.wide { grid-column: 1 / -1; }
.document-note, dt, .document-heading p, .subject-tree > p { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.document-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; border-bottom: 1px solid var(--erp-color-border); padding-bottom: 16px; }
.document-heading h2 { margin: 0; font-size: 22px; line-height: 30px; overflow-wrap: anywhere; }
.document-heading p { margin: 6px 0 0; }
.document-facts { margin: 0; }
.document-facts dd { margin: 4px 0 0; font-size: 14px; line-height: 24px; overflow-wrap: anywhere; }
.document-note, .path-display { margin: 0; overflow-wrap: anywhere; }
.latest-version { padding-top: 16px; border-top: 1px solid var(--erp-color-border); }
.subject-tree { display: grid; gap: 12px; }
.subject-tree .tree-frame { height: 360px; flex: none; }
.tree-breadcrumb { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
@media (max-width: 1100px) {
  .finance-subjects .erp-list-heading h1 { font-size: 28px !important; line-height: 36px !important; }
  .finance-subjects .erp-list-footer { height: auto; flex-wrap: wrap; }
}
@media (max-width: 600px) {
  .finance-subjects .erp-list-heading h1 { font-size: 24px !important; line-height: 32px !important; }
  .finance-subjects .erp-list-filters > label { width: 100%; }
  .finance-subjects .erp-list-filters label:first-child .el-input, .finance-subjects .erp-list-filters .el-select { width: 100%; }
  .finance-subjects .erp-list-filter-actions, .finance-subjects .erp-list-toolbar { flex-wrap: wrap; margin-left: 0; }
  .form-grid, .document-facts { grid-template-columns: 1fr; }
  .finance-subjects :deep(.el-table-fixed-column--right), .subject-tree :deep(.el-table-fixed-column--right) { position: static !important; }
}
@media (prefers-reduced-motion: reduce) {
  .finance-subjects, .finance-subject-dialog, .subject-tree { &, :deep(*), :deep(*::before), :deep(*::after) { animation: none !important; transition: none !important; } }
}
</style>
<style>
.finance-subject-popper .danger-action { color: var(--el-color-danger); }
@media (prefers-reduced-motion: reduce) {
  .finance-subject-popper, .finance-subject-popper *, .finance-subject-confirm, .finance-subject-confirm *, .finance-subject-overlay, .finance-subject-overlay * { animation: none !important; transition: none !important; }
}
</style>
