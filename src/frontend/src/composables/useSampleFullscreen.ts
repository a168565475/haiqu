import { nextTick, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export function useSampleFullscreen(root: Ref<HTMLElement | undefined>) {
  const fullscreen = ref(false)
  let previousFocus: HTMLElement | null = null
  async function toggleFullscreen() {
    if (!fullscreen.value) previousFocus = document.activeElement as HTMLElement | null
    fullscreen.value = !fullscreen.value
    await nextTick()
    if (fullscreen.value) root.value?.querySelector<HTMLButtonElement>('.fullscreen-header button')?.focus()
    else previousFocus?.focus()
  }
  function keydown(event: KeyboardEvent) {
    if (event.key !== 'Escape' || !fullscreen.value || event.defaultPrevented) return
    // 确认框与下拉框先消费 Escape；同一次按键不能同时取消操作和退出全屏。
    const insidePopup = event.composedPath().some(node => node instanceof Element && node.matches(
      '.el-select, .el-select-dropdown, .el-dialog, .el-message-box, [role="dialog"], [role="alertdialog"]',
    ))
    if (!insidePopup) void toggleFullscreen()
  }
  onMounted(() => window.addEventListener('keydown', keydown))
  onBeforeUnmount(() => window.removeEventListener('keydown', keydown))
  return { fullscreen, toggleFullscreen }
}
