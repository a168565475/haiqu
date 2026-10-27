<script setup lang="ts">
import { Box, Document, TrendCharts, User } from '@element-plus/icons-vue'
import type {
  CustomerAddress,
  CustomerDetail,
  CustomerDictionaryOption,
  CustomerDuplicateMatch,
  CustomerOptions,
  CustomerRegionOption,
} from '@/types/customer'

interface AddressDraft {
  addressType: string
  countryCode: string
  stateProvince: string
  city: string
  postalCode: string
  addressLine1: string
  addressLine2: string
  recipientName: string
  recipientPhone: string
}

interface EditForm {
  accountName: string
  shortName: string
  entityLegalName: string
  website: string
  primaryRegionId: string
  secondaryRegionId: string
  taxIdentifier: string
  addressCountryCode: string
  stateProvince: string
  city: string
  postalCode: string
  addressLine1: string
  recipientName: string
  recipientPhone: string
  typeIds: string[]
  sourceId: string
  gradeId: string
  industryId: string
  interestedProductIds: string[]
  inquiryKeywords: string
  lifecycleStage: string
}

interface EditDisplayForm {
  defaultLanguage: string
  addressType: string
}

const props = defineProps<{
  customer: CustomerDetail
  customerUpdatedLabel: string
  options: CustomerOptions | null
  duplicateMatches: CustomerDuplicateMatch[]
  checkingDuplicate: boolean
  profileCompleteness: number
  editCompletedCount: number
  editIsDirty: boolean
  editActiveSection: string
  editForm: EditForm
  editDisplayForm: EditDisplayForm
  secondaryRegionOptions: CustomerRegionOption[]
  addresses: CustomerAddress[]
  activeAddressId: string
  creatingNewAddress: boolean
  appendedAddressDrafts: AddressDraft[]
  sourceSalespersonNames: string
  sourceManagerNames: string
  saving: boolean
  formatCountryOption: (item: CustomerDictionaryOption) => string
  formatAddressOption: (address: CustomerAddress) => string
}>()

const emit = defineEmits<{
  'back-to-list': []
  cancel: []
  'scroll-section': [section: string]
  'select-address': [addressId: string]
  'start-add-address': []
  'remove-address': [index: number]
  save: [returnAfterSave: boolean, asDraft?: boolean]
}>()
</script>

<template>
  <main class="edit-page">
    <header class="edit-page-header">
      <p>客户管理 / 客户列表 / 客户编辑</p>
      <div class="edit-title-row">
        <div><h1>编辑客户</h1><ElTag type="success">正常</ElTag><span>{{ props.customer.account_code }} · {{ props.customer.account_name }}</span></div>
        <div><small>最后保存：{{ props.customerUpdatedLabel }}</small><ElButton @click="emit('back-to-list')">返回列表</ElButton></div>
      </div>
    </header>

    <ElAlert v-if="props.duplicateMatches.length" class="edit-duplicate-alert" type="warning" :title="`发现 ${props.duplicateMatches.length} 个疑似重复客户，已排除当前客户`" show-icon :closable="false" />

    <section class="edit-workspace">
      <aside class="edit-section-nav">
        <div class="edit-progress"><strong>客户资料</strong><span>资料完整度 {{ props.profileCompleteness }}%</span><ElProgress :percentage="props.profileCompleteness" :show-text="false" :stroke-width="4" /></div>
        <button :class="{ active: props.editActiveSection === 'profile' }" type="button" @click="emit('scroll-section', 'profile')"><ElIcon><Document /></ElIcon>主体资料</button>
        <button :class="{ active: props.editActiveSection === 'address' }" type="button" @click="emit('scroll-section', 'address')"><ElIcon><Box /></ElIcon>地址信息</button>
        <button :class="{ active: props.editActiveSection === 'attributes' }" type="button" @click="emit('scroll-section', 'attributes')"><ElIcon><TrendCharts /></ElIcon>客户属性</button>
        <button :class="{ active: props.editActiveSection === 'ownership' }" type="button" @click="emit('scroll-section', 'ownership')"><ElIcon><User /></ElIcon>归属与标签</button>
        <div class="edit-nav-tip"><strong>{{ props.editCompletedCount }} / 11 项必填已完成</strong><span>保存时将统一校验</span></div>
      </aside>

      <ElForm label-position="top" class="edit-form">
        <section id="edit-section-profile" class="edit-form-card profile-card">
          <header><div><ElIcon><Document /></ElIcon><strong>主体资料</strong><span>带 * 为必填</span></div><small v-if="props.checkingDuplicate">正在查重…</small></header>
          <div class="figma-form-grid">
            <ElFormItem label="客户名称 *" required><ElInput v-model="props.editForm.accountName" /></ElFormItem><ElFormItem label="客户简称"><ElInput v-model="props.editForm.shortName" /></ElFormItem><ElFormItem label="法定主体名称"><ElInput v-model="props.editForm.entityLegalName" /></ElFormItem><ElFormItem label="网站 / 域名"><ElInput v-model="props.editForm.website" /></ElFormItem>
            <ElFormItem label="一级地区 *" required><ElSelect v-model="props.editForm.primaryRegionId" filterable><ElOption v-for="item in props.options?.primary_regions" :key="item.id" :label="item.region_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="二级地区"><ElSelect v-model="props.editForm.secondaryRegionId" filterable clearable :disabled="!props.editForm.primaryRegionId"><ElOption v-for="item in props.secondaryRegionOptions" :key="item.id" :label="item.region_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="默认语言"><ElSelect v-model="props.editDisplayForm.defaultLanguage"><ElOption label="English" value="English" /><ElOption label="简体中文" value="简体中文" /></ElSelect></ElFormItem><ElFormItem label="税号 / 注册号"><ElInput v-model="props.editForm.taxIdentifier" /></ElFormItem>
          </div>
        </section>

        <section id="edit-section-address" class="edit-form-card address-card">
          <header>
            <div><ElIcon><Box /></ElIcon><strong>地址信息</strong><small>已保存 {{ props.addresses.length }} 条</small><ElTag v-if="props.creatingNewAddress" type="success" size="small">待新增 {{ props.appendedAddressDrafts.length }} 条</ElTag></div>
            <div class="address-actions">
              <ElSelect v-if="props.addresses.length" :model-value="props.activeAddressId" size="small" @update:model-value="emit('select-address', $event)"><ElOption v-for="address in props.addresses" :key="address.id" :label="props.formatAddressOption(address)" :value="address.id" /></ElSelect>
              <ElButton text @click="emit('start-add-address')">＋ 添加地址</ElButton>
            </div>
          </header>
          <div class="figma-form-grid">
            <ElFormItem label="地址类型 *" required><ElSelect v-model="props.editDisplayForm.addressType"><ElOption label="办公地址" value="办公地址" /><ElOption label="收货地址" value="收货地址" /></ElSelect></ElFormItem><ElFormItem label="国家 / 地区 *" required><ElSelect v-model="props.editForm.addressCountryCode"><ElOption v-for="item in props.options?.country_options" :key="item.id" :label="props.formatCountryOption(item)" :value="item.item_code" :disabled="item.disabled" /></ElSelect></ElFormItem><ElFormItem label="州 / 省"><ElInput v-model="props.editForm.stateProvince" /></ElFormItem><ElFormItem label="城市"><ElInput v-model="props.editForm.city" /></ElFormItem>
            <ElFormItem label="详细地址 *" required><ElInput v-model="props.editForm.addressLine1" /></ElFormItem><ElFormItem label="邮编"><ElInput v-model="props.editForm.postalCode" /></ElFormItem><ElFormItem label="收货联系人"><ElInput v-model="props.editForm.recipientName" /></ElFormItem><ElFormItem label="收货电话"><ElInput v-model="props.editForm.recipientPhone" /></ElFormItem>
          </div>
          <div v-for="(draft, index) in props.appendedAddressDrafts" :key="index" class="appended-address-block">
            <div class="appended-address-heading"><strong>新增地址 {{ index + 1 }}</strong><ElButton text type="danger" @click="emit('remove-address', index)">删除此条</ElButton></div>
            <div class="figma-form-grid">
              <ElFormItem label="地址类型 *" required><ElSelect v-model="draft.addressType"><ElOption label="办公地址" value="办公地址" /><ElOption label="收货地址" value="收货地址" /></ElSelect></ElFormItem><ElFormItem label="国家 / 地区 *" required><ElSelect v-model="draft.countryCode"><ElOption v-for="item in props.options?.country_options" :key="item.id" :label="props.formatCountryOption(item)" :value="item.item_code" :disabled="item.disabled" /></ElSelect></ElFormItem><ElFormItem label="州 / 省"><ElInput v-model="draft.stateProvince" /></ElFormItem><ElFormItem label="城市"><ElInput v-model="draft.city" /></ElFormItem>
              <ElFormItem label="详细地址 *" required><ElInput v-model="draft.addressLine1" /></ElFormItem><ElFormItem label="邮编"><ElInput v-model="draft.postalCode" /></ElFormItem><ElFormItem label="收货联系人"><ElInput v-model="draft.recipientName" /></ElFormItem><ElFormItem label="收货电话"><ElInput v-model="draft.recipientPhone" /></ElFormItem>
            </div>
          </div>
        </section>

        <section id="edit-section-attributes" class="edit-form-card attributes-card">
          <header><div><ElIcon><TrendCharts /></ElIcon><strong>客户属性</strong></div></header>
          <div class="figma-form-grid">
            <ElFormItem label="客户类型 *" required><ElSelect v-model="props.editForm.typeIds" multiple collapse-tags><ElOption v-for="item in props.options?.customer_types" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem><ElFormItem label="客户来源 *" required><ElSelect v-model="props.editForm.sourceId"><ElOption v-for="item in props.options?.customer_sources" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem><ElFormItem label="客户等级 *" required><ElSelect v-model="props.editForm.gradeId"><ElOption v-for="item in props.options?.customer_grades" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
            <ElFormItem label="所属行业"><ElSelect v-model="props.editForm.industryId" clearable><ElOption v-for="item in props.options?.industries" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="感兴趣产品"><ElSelect v-model="props.editForm.interestedProductIds" multiple collapse-tags clearable><ElOption v-for="item in props.options?.interested_products" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="询盘关键词"><ElInput v-model="props.editForm.inquiryKeywords" /></ElFormItem><ElFormItem label="生命周期"><ElSelect v-model="props.editForm.lifecycleStage"><ElOption v-for="item in props.options?.lifecycle_stages" :key="item.item_code" :label="item.display_name" :value="item.item_code" /></ElSelect></ElFormItem>
          </div>
        </section>

        <section id="edit-section-ownership" class="edit-form-card ownership-card">
          <header><div><ElIcon><User /></ElIcon><strong>归属与标签</strong></div></header>
          <div class="figma-form-grid ownership-fields">
            <ElFormItem label="负责人 *" required><ElInput :model-value="props.customer.primary_owner?.display_name || ''" readonly /></ElFormItem>
            <ElFormItem label="业务员"><ElInput :model-value="props.sourceSalespersonNames" readonly /></ElFormItem>
            <ElFormItem label="分管人"><ElInput :model-value="props.sourceManagerNames" readonly /></ElFormItem>
          </div>
        </section>
      </ElForm>
    </section>

    <footer class="edit-action-bar">
      <span><i :class="{ saved: !props.editIsDirty }"></i>{{ props.editIsDirty ? '有未保存修改 · 保存时将校验全部必填项' : '所有修改已保存' }}</span>
      <div><ElButton @click="emit('cancel')">取消</ElButton><ElButton :loading="props.saving" @click="emit('save', false, true)">保存草稿</ElButton><ElButton :loading="props.saving" @click="emit('save', true)">保存并返回</ElButton><ElButton type="primary" :loading="props.saving" @click="emit('save', false)">保存</ElButton></div>
    </footer>
  </main>
</template>

<style scoped lang="scss">
.edit-page { width: min(1320px, calc(100% - 48px)); margin: 24px auto 0; padding-bottom: 24px; }
.edit-page-header { height: 72px; }
.edit-page-header > p { margin: 0 0 8px; color: var(--erp-color-text-regular); font-size: 12px; line-height: 14px; }
.edit-title-row, .edit-title-row > div { display: flex; align-items: center; }
.edit-title-row { height: 44px; justify-content: space-between; }
.edit-title-row > div { gap: 12px; }
.edit-title-row h1 { margin: 0; color: var(--erp-color-text-primary); font-size: 26px; line-height: 32px; }
.edit-title-row span, .edit-title-row small { color: var(--erp-color-text-regular); font-size: 13px; }
.edit-title-row :deep(.el-tag) { width: 72px; height: 24px; border: 0; border-radius: 6px; }
.edit-title-row :deep(.el-button) { width: 96px; height: 32px; margin-left: 0; border-color: var(--erp-color-border); border-radius: 8px; }
.edit-duplicate-alert { margin-bottom: 8px; }
.edit-workspace { height: 808px; display: grid; grid-template-columns: 196px minmax(0, 1fr); overflow: hidden; margin-top: 16px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-surface); box-shadow: 0 8px 18px color-mix(in srgb, var(--erp-shadow-color) 10%, transparent); }
.edit-section-nav { padding: 24px 16px; border-right: 1px solid var(--erp-color-border); background: var(--erp-color-surface); }
.edit-progress { height: 46px; display: flex; flex-direction: column; gap: 3px; margin-bottom: 8px; }
.edit-progress strong { color: var(--erp-color-text-primary); font-size: 14px; line-height: 17px; }
.edit-progress span { color: var(--erp-color-text-regular); font-size: 11px; line-height: 13px; }
.edit-progress :deep(.el-progress-bar__outer) { background: var(--erp-color-subtle); }
.edit-progress :deep(.el-progress-bar__inner) { background: var(--erp-color-surface); }
.edit-section-nav > button { width: 164px; height: 40px; display: flex; align-items: center; gap: 10px; margin: 0 0 8px; padding: 0 12px; border: 0; border-radius: 8px; color: var(--erp-color-text-primary); background: transparent; font-size: 13px; cursor: pointer; }
.edit-section-nav > button:hover { background: var(--erp-color-hover); }
.edit-section-nav > button.active { color: var(--erp-color-text-primary); background: var(--erp-color-selected); font-weight: 600; }
.edit-section-nav > button :deep(.el-icon) { width: 20px; height: 20px; font-size: 20px; }
.edit-nav-tip { height: 66px; display: flex; flex-direction: column; gap: 4px; margin-top: 8px; padding: 10px; border: 1px solid var(--erp-color-border); border-radius: 7px; background: var(--erp-color-surface); }
.edit-nav-tip strong { font-size: 11px; line-height: 14px; }
.edit-nav-tip span { color: var(--erp-color-text-regular); font-size: 10px; }
.edit-form { height: 808px; display: flex; flex-direction: column; gap: 12px; overflow-y: auto; padding: 24px; scroll-behavior: smooth; }
.edit-form-card { flex: none; box-sizing: border-box; padding: 12px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-surface); scroll-margin-top: 24px; }
.edit-form-card.profile-card { height: 182px; }
.edit-form-card.address-card { min-height: 180px; }
.edit-form-card.attributes-card { height: 170px; padding-top: 10px; }
.edit-form-card.ownership-card { height: 192px; }
.edit-form-card > header { height: 20px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.edit-form-card > header > div { display: flex; align-items: center; gap: 8px; }
.edit-form-card > header strong { color: var(--erp-color-text-primary); font-size: 14px; line-height: 17px; }
.edit-form-card > header span, .edit-form-card > header small { color: var(--erp-color-text-regular); font-size: 10px; }
.edit-form-card > header :deep(.el-icon) { width: 20px; height: 20px; color: var(--erp-color-text-regular); font-size: 20px; }
.edit-form-card > header :deep(.el-button) { height: 28px; padding: 0 12px; color: var(--erp-color-text-primary); font-size: 12px; }
.address-actions { display: flex; align-items: center; gap: 6px; }
.address-actions :deep(.el-select) { width: 172px; }
.address-actions :deep(.el-select__wrapper) { min-height: 28px; }
.appended-address-block { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--erp-color-border); }
.appended-address-heading { height: 28px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.appended-address-heading strong { color: var(--erp-color-text-primary); font-size: 12px; }
.appended-address-heading :deep(.el-button) { height: 28px; margin: 0; padding: 0 4px; font-size: 11px; }
.figma-form-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px 16px; }
.figma-form-grid :deep(.el-form-item) { height: 52px; margin: 0; }
.figma-form-grid :deep(.el-form-item__label) { height: 17px; margin: 0; padding: 0; color: var(--erp-color-text-secondary); font-size: 11px; line-height: 13px; }
.figma-form-grid :deep(.el-form-item__content) { height: 32px; line-height: 32px; }
.figma-form-grid :deep(.el-select), .figma-form-grid :deep(.el-input) { width: 100%; }
.figma-form-grid :deep(.el-input__wrapper), .figma-form-grid :deep(.el-select__wrapper) { min-height: 32px; padding: 0 12px; border-radius: 8px; box-shadow: 0 0 0 1px var(--erp-color-border) inset; }
.figma-form-grid :deep(.el-input__inner), .figma-form-grid :deep(.el-select__placeholder), .figma-form-grid :deep(.el-select__selected-item) { color: var(--erp-input-text); font-size: 13px; }
.edit-action-bar { height: 56px; display: flex; align-items: center; justify-content: space-between; margin-top: 16px; padding: 0 16px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-surface); }
.edit-action-bar > span { display: flex; align-items: center; gap: 8px; color: var(--erp-color-text-regular); font-size: 11px; }
.edit-action-bar i { width: 8px; height: 8px; border-radius: 50%; background: var(--erp-color-warning); }
.edit-action-bar i.saved { background: var(--erp-color-success); }
.edit-action-bar > div { display: flex; gap: 8px; }
.edit-action-bar :deep(.el-button) { width: 96px; height: 32px; margin: 0; border-radius: 8px; }
.edit-action-bar :deep(.el-button--primary) { border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-surface); }

@media (max-width: 1200px) {
  .edit-page { width: calc(100% - 32px); }
  .edit-workspace { grid-template-columns: 168px minmax(0, 1fr); }
  .edit-section-nav { padding-inline: 10px; }
  .edit-section-nav > button { width: 146px; }
  .figma-form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .edit-form-card.profile-card, .edit-form-card.attributes-card { height: 300px; }
  .edit-form-card.address-card { min-height: 300px; }
  .edit-form-card.ownership-card { height: 240px; }
}

@media (max-width: 800px) {
  .edit-page { width: calc(100% - 24px); margin-top: 12px; }
  .edit-title-row, .edit-title-row > div, .edit-action-bar { align-items: flex-start; flex-direction: column; }
  .edit-page-header { height: auto; margin-bottom: 12px; }
  .edit-title-row { height: auto; gap: 12px; }
  .edit-workspace { height: auto; display: block; }
  .edit-section-nav { display: none; }
  .edit-form { height: auto; overflow: visible; padding: 12px; }
  .figma-form-grid { grid-template-columns: 1fr; }
  .edit-form-card.profile-card, .edit-form-card.address-card, .edit-form-card.attributes-card, .edit-form-card.ownership-card { height: auto; }
  .edit-action-bar { height: auto; gap: 12px; padding: 12px; }
  .edit-action-bar > div { width: 100%; flex-wrap: wrap; }
}
</style>
