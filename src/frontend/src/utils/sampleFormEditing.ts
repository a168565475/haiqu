import type { SampleDetail, SampleReportingProductEdit, SampleRequestFormInput } from '@/types/sample'

/** 仅报工阶段使用读取快照保留不可编辑数据，不从显示表单重新推断来源、数量或图片。 */
export function buildSampleReportingPayload(
  sample: SampleDetail,
  edits: SampleReportingProductEdit[],
  purpose: string,
): SampleRequestFormInput {
  if (sample.edit_capabilities?.mode !== 'REPORT_ONLY' || !sample.edit_capabilities.can_report_edit) {
    throw new Error('当前申请不允许修改报工信息，请重新加载。')
  }
  if (purpose.length > 2000) throw new Error('特殊说明不能超过 2000 字。')
  const originalProducts = sample.products || []
  if (!originalProducts.length || edits.length !== originalProducts.length || new Set(edits.map(item => item.id)).size !== edits.length) {
    throw new Error('产品信息不完整，请重新加载后再保存。')
  }
  if (!sample.manual_request_number || !sample.owner?.id || !sample.shipping_method || !sample.order_date || !sample.sample_due_date || !sample.delivery_batch || !sample.submitted_on || sample.is_repeat_order == null) {
    throw new Error('申请基础数据不完整，无法安全保存报工信息。')
  }
  return {
    manual_request_number: sample.manual_request_number,
    customer_account_id: sample.customer_account,
    customer_contact_id: sample.customer_contact,
    owner_employee_id: sample.owner.id,
    shipping_method: sample.shipping_method,
    order_date: sample.order_date,
    sample_due_date: sample.sample_due_date,
    delivery_batch: sample.delivery_batch,
    sample_type: sample.sample_type,
    is_repeat_order: sample.is_repeat_order,
    submitted_on: sample.submitted_on,
    purpose,
    products: originalProducts.map(product => {
      const edit = edits.find(item => item.id === product.id)
      if (!edit || !product.category_id || edit.details.length !== product.details.length || new Set(edit.details.map(item => item.id)).size !== edit.details.length) {
        throw new Error('产品或报工行与原申请不一致，请重新加载。')
      }
      return {
        id: product.id,
        client_key: product.id,
        source_inquiry_item_id: product.source_inquiry_item_id,
        source_quotation_line_id: product.source_quotation_line_id,
        category_id: product.category_id,
        product_name: product.product_name,
        specification: product.specification,
        length_cm: product.length_cm,
        armrest_width_cm: product.armrest_width_cm,
        seat_width_cm: product.seat_width_cm,
        back_height_cm: product.back_height_cm,
        seat_height_cm: product.seat_height_cm,
        details: product.details.map(detail => {
          const change = edit.details.find(item => item.id === detail.id)
          const quantity = detail.sample_quantity
          if (!change || !detail.product_color_id || quantity == null || !Number.isSafeInteger(quantity) || quantity <= 0) {
            throw new Error('原申请的数量或颜色数据不完整，无法安全保存报工信息。')
          }
          // 输入框清空等于零，与原报工输入语义一致；拒绝小数、负数、越界及非数值。
          const cutting = change.cutting_reported_quantity ?? 0
          const metalwork = change.metalwork_reported_quantity ?? 0
          if (!Number.isSafeInteger(cutting) || cutting < 0 || cutting > quantity || !Number.isSafeInteger(metalwork) || metalwork < 0 || metalwork > quantity) {
            throw new Error('报工数量必须是 0 到打样数量之间的整数。')
          }
          if (typeof change.cutting_completed !== 'boolean' || typeof change.metalwork_completed !== 'boolean') {
            throw new Error('请选择裁剪和金工的完成状态。')
          }
          return {
            id: detail.id,
            product_color_id: detail.product_color_id,
            color_code: detail.color_code,
            sample_quantity: quantity,
            tolerance: detail.tolerance,
            notes: detail.notes,
            cutting_reported_quantity: cutting,
            metalwork_reported_quantity: metalwork,
            cutting_completed: change.cutting_completed,
            metalwork_completed: change.metalwork_completed,
          }
        }),
        sampling_details: (product.sampling_details || []).map(detail => ({
          id: detail.id,
          client_key: detail.id,
          template_key: detail.template_key,
          detail_type: detail.detail_type,
          category_label: detail.category_label,
          is_selected: detail.is_selected,
          description: detail.description,
        })),
      }
    }),
  }
}
