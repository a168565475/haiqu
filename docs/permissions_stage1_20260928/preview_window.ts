import { createApp, h, reactive } from 'vue'
import AppWindowDialog from '../../src/frontend/src/components/common/AppWindowDialog.vue'

type Action = { text: string; primary?: boolean; run: () => void }
const state = reactive({ visible: false, title: '', body: '', actions: [] as Action[] })
const bridge = {
  open(title: string, body: string, actions: Action[]) {
    Object.assign(state, { title, body, actions, visible: true })
  },
  close() { state.visible = false },
}
// Static, local demonstration only. No authentication, storage or API clients.
Object.assign(window, { erpPreviewWindow: bridge })
createApp({
  setup: () => () => h(AppWindowDialog, {
    modelValue: state.visible,
    'onUpdate:modelValue': (visible: boolean) => { state.visible = visible },
    title: state.title, width: 720, destroyOnClose: true,
  }, {
    default: () => h('div', { id: 'dialogBody', innerHTML: state.body }),
    footer: () => h('div', { class: 'actions dialog-actions' }, state.actions.map(action =>
      h('button', { class: action.primary ? 'primary' : '', onClick: action.run }, action.text))),
  }),
}).mount('#previewWindowMount')
