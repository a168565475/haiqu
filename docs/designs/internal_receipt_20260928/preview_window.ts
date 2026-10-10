import { createApp, h, reactive } from 'vue'
import AppWindowDialog from '../../../src/frontend/src/components/common/AppWindowDialog.vue'

const state = reactive({ visible: false, title: '', body: '' })
// 独立设计预览：复用正式窗口组件，仅在内存中展示示例来源，不调用业务接口。
const sourceWindow = {
  open(title: string, body: string) {
    Object.assign(state, { title, body, visible: true })
  },
  close() { state.visible = false },
}
Object.assign(window, { receiptSourceWindow: sourceWindow })
createApp({
  setup: () => () => h(AppWindowDialog, {
    modelValue: state.visible,
    'onUpdate:modelValue': (visible: boolean) => { state.visible = visible },
    title: state.title, width: 1180, height: 660,
    destroyOnClose: true, class: 'receipt-source-window',
  }, {
    default: () => h('div', { id: 'sourceDetailBody', innerHTML: state.body }),
    footer: () => h('div', { class: 'source-window-footer' }, [
      h('span', { class: 'muted' }, '来源详情只读'),
      h('button', { onClick: sourceWindow.close }, '关闭'),
    ]),
  }),
}).mount('#sourceWindowMount')
