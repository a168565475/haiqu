<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import '../board.scss'
import '../boardMotion.scss'
import '../boardChrome.scss'

const props = defineProps<{ title: string }>()
const root = ref<HTMLElement>()
const now = ref(new Date())
const scale = ref(1)
const fullscreen = ref(false)
const fullscreenError = ref('')
const previousTitle = document.title
let clock: ReturnType<typeof setInterval> | undefined
const timestamp = computed(() => new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
}).format(now.value))

function resize() { scale.value = Math.min(window.innerWidth / 1920, window.innerHeight / 1080) }
function updateFullscreen() { fullscreen.value = document.fullscreenElement === root.value }
async function toggleFullscreen() {
  fullscreenError.value = ''
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else if (root.value?.requestFullscreen) await root.value.requestFullscreen()
    else fullscreenError.value = '浏览器暂不支持全屏，可使用 F11。'
  } catch {
    fullscreenError.value = '浏览器未允许全屏，请使用 F11 或重试。'
  }
}

onMounted(() => {
  document.title = `${props.title} · 演示看板`
  resize()
  clock = setInterval(() => { now.value = new Date() }, 1000)
  window.addEventListener('resize', resize)
  document.addEventListener('fullscreenchange', updateFullscreen)
})
onBeforeUnmount(() => {
  clearInterval(clock)
  window.removeEventListener('resize', resize)
  document.removeEventListener('fullscreenchange', updateFullscreen)
  document.title = previousTitle
})
</script>

<template>
  <main ref="root" class="board-page" :aria-label="`${title}，模拟数据演示`">
    <div class="board-canvas" :style="{ transform: `translate(-50%, -50%) scale(${scale})` }">
      <header class="board-header">
        <svg class="board-header-decoration" viewBox="0 0 1920 88" aria-hidden="true">
          <defs>
            <linearGradient id="board-chevron-fill" x2="0" y2="1"><stop stop-color="#c3f779" /><stop offset="1" stop-color="#00cca5" /></linearGradient>
          </defs>
          <g fill="url(#board-chevron-fill)">
            <path class="board-header-sweep" style="--board-sweep-step: 0" d="M442 42h16l20 25h-16z" opacity=".25" />
            <path class="board-header-sweep" style="--board-sweep-step: 1" d="M473 42h16l20 25h-16z" opacity=".5" />
            <path class="board-header-sweep" style="--board-sweep-step: 2" d="M504 42h16l20 25h-16z" opacity=".75" />
            <path class="board-header-sweep" style="--board-sweep-step: 3" d="M535 42h16l20 25h-16z" />
            <path class="board-header-sweep" style="--board-sweep-step: 3" d="M1370 42h16l-20 25h-16z" />
            <path class="board-header-sweep" style="--board-sweep-step: 2" d="M1401 42h16l-20 25h-16z" opacity=".75" />
            <path class="board-header-sweep" style="--board-sweep-step: 1" d="M1432 42h16l-20 25h-16z" opacity=".5" />
            <path class="board-header-sweep" style="--board-sweep-step: 0" d="M1463 42h16l-20 25h-16z" opacity=".25" />
          </g>
        </svg>
        <time class="board-clock">{{ timestamp }}</time>
        <h1>{{ title }}</h1>
        <span class="board-demo-badge">演示数据 · 不写入数据库</span>
        <div class="board-header-actions">
          <button type="button" :aria-label="fullscreen ? '退出全屏' : '进入全屏'" :title="fullscreen ? '退出全屏' : '进入全屏'" @click="toggleFullscreen">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5M3 3l6 6m12-6-6 6m6 12-6-6M3 21l6-6" /></svg>
          </button>
          <RouterLink :to="{ name: 'home' }" aria-label="返回 ERP" title="返回 ERP">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v10M6 4.5a9 9 0 1 0 12 0" /></svg>
          </RouterLink>
        </div>
        <span v-if="fullscreenError" class="board-fullscreen-error" role="alert">{{ fullscreenError }}</span>
      </header>
      <div class="board-content"><slot /></div>
    </div>
  </main>
</template>
