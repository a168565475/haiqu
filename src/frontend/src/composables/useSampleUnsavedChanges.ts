import { onBeforeUnmount, onMounted } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessageBox } from 'element-plus'

/** 页面切换与浏览器关闭使用同一份未保存判断；全屏切换不离开路由。 */
export function useSampleUnsavedChanges(isDirty: () => boolean, title = '离开填写页') {
  async function confirmLeave() {
    if (!isDirty()) return true
    try {
      await ElMessageBox.confirm('填写内容尚未保存，确定离开？', title, {
        confirmButtonText: '离开', cancelButtonText: '继续填写', type: 'warning',
      })
      return true
    } catch { return false }
  }
  function beforeUnload(event: BeforeUnloadEvent) {
    if (isDirty()) { event.preventDefault(); event.returnValue = '' }
  }
  onBeforeRouteLeave(confirmLeave)
  // App.vue 按 fullPath 重建页面；同一路由的参数变化同样会丢弃输入。
  onBeforeRouteUpdate(confirmLeave)
  onMounted(() => window.addEventListener('beforeunload', beforeUnload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
}
