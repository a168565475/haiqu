<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import documentLockIcon from '@/assets/procurement/publish-document-lock.svg'
import infoIcon from '@/assets/procurement/publish-info.svg'

const visible = defineModel<boolean>({ required: true })
const props = defineProps<{
  sheetNumber: string
  version: number
  supplierName: string
  templateName: string
  amount: string
  lineCount: number
  hasSeal: boolean
  publishing: boolean
  error: string
  blocked: boolean
}>()
defineEmits<{ confirm: [] }>()
function close(): void {
  if (!props.publishing) visible.value = false
}
</script>

<template>
  <ElDialog v-model="visible" class="purchase-publish-dialog" title="发布采购表" width="646px"
    append-to-body destroy-on-close :close-on-click-modal="false" :close-on-press-escape="!publishing"
    :before-close="close" :aria-busy="publishing">
    <p class="publish-subtitle">确认当前版本，生成正式 PDF</p>
    <dl class="publish-summary">
      <div><dt>采购表编号</dt><dd class="publish-number"><span :title="sheetNumber">{{ sheetNumber || '—' }}</span><ElTag>V{{ version }}</ElTag></dd></div>
      <div><dt>供应商</dt><dd :title="supplierName">{{ supplierName || '—' }}</dd></div>
      <div><dt>合同模板</dt><dd :title="templateName">{{ templateName || '—' }}</dd></div>
      <div><dt>采购金额</dt><dd class="publish-amount"><strong :title="amount">{{ amount }}</strong><span>共 {{ lineCount }} 项明细</span></dd></div>
    </dl>
    <div class="publish-notices">
      <div class="publish-lock-notice">
        <img :src="documentLockIcon" alt="" width="38" height="38" />
        <div><p>发布后，当前 V{{ version }} 版本将锁定为只读。</p><p>如需修改，请创建新版本。</p></div>
      </div>
      <div class="publish-seal-notice">
        <span class="publish-info-icon"><img :src="infoIcon" alt="" width="21" height="21" /></span>
        <p v-if="hasSeal">已上传甲方盖章图片<br />正式 PDF 将带入已上传的盖章图片。</p>
        <p v-else>当前未上传甲方盖章图片<br />正式 PDF 将保留签章位置。</p>
      </div>
    </div>
    <p v-if="error" class="publish-error" role="alert">{{ error }}</p>
    <template #footer>
      <ElButton :disabled="publishing" @click="close">返回编辑</ElButton>
      <ElButton type="primary" :loading="publishing" :disabled="publishing || blocked" @click="$emit('confirm')">{{ publishing ? '正在发布…' : '确认发布' }}</ElButton>
    </template>
  </ElDialog>
</template>

<style lang="scss">
@use '@/styles/crm/tokens' as crm;
.el-dialog.purchase-publish-dialog {
  box-sizing: border-box; padding: 0; margin-bottom: 0;
  min-height: 672px; border-radius: 6px; background: crm.$crm-color-surface; color: crm.$crm-text-primary;
  box-shadow: 0 8px 24px #00000029; font-family: crm.$crm-font-body;
  --el-color-primary: #{crm.$crm-primary}; --el-color-primary-light-3: #{crm.$crm-primary-light-3};
  --el-fill-color-blank: #{crm.$crm-color-surface}; --el-border-color: #{crm.$crm-border-default};
  --el-text-color-regular: #{crm.$crm-text-primary};
  .el-dialog__header { box-sizing: border-box; position: relative; height: 154px; padding: 34px 44px 0; margin: 0; }
  .el-dialog__header::after { content: ''; position: absolute; left: 44px; right: 44px; top: 152px; height: 1px; background: crm.$crm-border-default; }
  .el-dialog__headerbtn { top: 24px; right: 26px; width: 32px; height: 32px; font-size: 20px; }
  .el-dialog__close { color: crm.$crm-text-secondary; }
  &[aria-busy=true] .el-dialog__headerbtn { cursor: wait; }
  h2 { margin: 0; font: 700 44px/60px crm.$crm-font-display; }
  .publish-subtitle { margin: 8px 0 0; font-size: 20px; line-height: 28px; color: crm.$crm-text-secondary; }
  .el-dialog__body { padding: 0; color: crm.$crm-text-primary; }
  .publish-summary { box-sizing: border-box; height: 220px; padding: 22px 44px 18px; margin: 0; }
  .publish-summary > div { display: flex; align-items: center; height: 45px; font-size: 20px; line-height: 30px; }
  dt { width: 156px; flex-shrink: 0; color: crm.$crm-text-secondary; }
  dd { min-width: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .publish-number { display: flex; align-items: center; gap: 14px; }
  .publish-number > span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .publish-number .el-tag { flex-shrink: 0; width: 68px; height: 36px; border: 0; border-radius: 999px; padding: 0; color: crm.$crm-neutral; background: crm.$crm-color-subtle; font: 500 16px/22px crm.$crm-font-body; }
  .publish-amount { display: flex; align-items: center; gap: 12px; line-height: 36px; }
  .publish-amount strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; font-size: 28px; font-weight: 700; }
  .publish-amount > span { display: flex; align-items: center; gap: 12px; flex-shrink: 0; font-size: 18px; color: crm.$crm-text-secondary; }
  .publish-amount > span::before { content: ''; width: 1px; height: 20px; background: crm.$crm-border-subtle; }
  .publish-notices { box-sizing: border-box; height: 206px; padding: 3px 44px 0; display: flex; flex-direction: column; gap: 14px; }
  .publish-notices p { margin: 0; }
  .publish-lock-notice { box-sizing: border-box; display: flex; align-items: center; gap: 26px; min-height: 90px; padding: 0 24px 0 30px; border: 1px solid crm.$crm-border-default; border-radius: 6px; background: crm.$crm-color-subtle; font-size: 18px; line-height: 28px; }
  .publish-lock-notice img { flex-shrink: 0; width: 38px; height: 38px; }
  .publish-lock-notice p + p { color: crm.$crm-text-secondary; }
  .publish-seal-notice { box-sizing: border-box; display: flex; align-items: center; gap: 24px; min-height: 76px; padding: 0 22px; border-radius: 6px; background: crm.$crm-warning-soft; color: crm.$crm-warning; font-size: 18px; line-height: 26px; }
  .publish-info-icon { display: flex; flex-shrink: 0; align-items: center; justify-content: center; width: 24px; height: 24px; }
  .publish-info-icon img { width: 21px; height: 21px; transform: rotate(180deg); }
  .publish-error { margin: 0; padding: 0 44px 18px; color: crm.$crm-danger; font-size: 16px; line-height: 24px; overflow-wrap: anywhere; }
  .el-dialog__footer { box-sizing: border-box; height: 92px; padding: 0 32px; display: flex; justify-content: flex-end; align-items: center; gap: 14px; border-top: 1px solid crm.$crm-border-subtle; }
  .el-dialog__footer .el-button { width: 144px; height: 52px; margin: 0; padding: 0 20px; border-radius: 5px; font: 500 16px/20px crm.$crm-font-body; }
}
</style>
