<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useId } from 'vue'

import collaborationImage from '@/assets/login/business-collaboration.png'

const paused = ref(false)
const clipPrefix = useId().replace(/[^A-Za-z0-9_-]/g, '')
const nodes = [
  { x: 192, y: 826, radius: 152, delay: '0s', clip: { x: 30, y: 525, width: 340, height: 430 } },
  { x: 552, y: 709, radius: 158, delay: '3.4s', clip: { x: 390, y: 414, width: 310, height: 390 } },
  { x: 852, y: 604, radius: 132, delay: '6.4s', clip: { x: 710, y: 343, width: 280, height: 360 } },
  { x: 1224, y: 520, radius: 170, delay: '9.2s', clip: { x: 975, y: 172, width: 470, height: 480 } },
]

function updateVisibility() { paused.value = document.hidden }
onMounted(() => {
  updateVisibility()
  document.addEventListener('visibilitychange', updateVisibility)
})
onBeforeUnmount(() => document.removeEventListener('visibilitychange', updateVisibility))
</script>

<template>
  <figure class="flow-illustration" :class="{ 'is-paused': paused }">
    <img
      class="flow-image"
      :src="collaborationImage"
      alt="客户、报价、订单与生产制造沿同一条业务链路协同"
      width="1448"
      height="1086"
    />
    <svg class="flow-light" viewBox="0 0 1448 1086" fill="none" aria-hidden="true">
      <defs>
        <clipPath v-for="(node, index) in nodes" :id="`${clipPrefix}-node-${index}`" :key="index">
          <rect v-bind="node.clip" />
        </clipPath>
      </defs>
      <g
        v-for="(node, index) in nodes"
        :key="`highlight-${index}`"
        class="flow-node-highlight"
        :style="{ '--node-delay': node.delay }"
      >
        <image :href="collaborationImage" width="1448" height="1086" :clip-path="`url(#${clipPrefix}-node-${index})`" />
      </g>
      <path
        class="flow-trail"
        d="M 192 826 C 325 826 414 741 552 709 S 737 650 852 604 S 1092 530 1224 520"
        pathLength="100"
      />
      <ellipse
        v-for="(node, index) in nodes"
        :key="index"
        class="flow-node"
        :cx="node.x"
        :cy="node.y"
        :rx="node.radius"
        ry="45"
        :style="{ '--node-delay': node.delay }"
      />
    </svg>
  </figure>
</template>

<style scoped>
.flow-illustration { position: relative; width: 100%; margin: 0; aspect-ratio: 1448 / 1086; }
.flow-image { display: block; width: 100%; height: auto; filter: none; }
.flow-light { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.flow-trail {
  stroke: #d5f8ff;
  stroke-width: 9px;
  stroke-linecap: round;
  stroke-dasharray: 4 96;
  filter: drop-shadow(0 0 9px #4fbdff);
  animation: business-flow 10s linear infinite;
}
.flow-node {
  fill: rgb(104 208 255 / 12%);
  stroke: #c9f4ff;
  stroke-width: 4px;
  opacity: 0;
  filter: drop-shadow(0 0 13px #4ebeff);
  animation: business-node 10s linear infinite;
  animation-delay: var(--node-delay);
}
.flow-node-highlight {
  opacity: 0;
  filter: brightness(1.15) saturate(1.08) drop-shadow(0 0 7px rgb(165 230 255 / 40%));
  animation: business-node 10s linear infinite;
  animation-delay: var(--node-delay);
}
.is-paused .flow-trail, .is-paused .flow-node, .is-paused .flow-node-highlight { animation-play-state: paused; }
@keyframes business-flow { from { stroke-dashoffset: 100; } to { stroke-dashoffset: 0; } }
@keyframes business-node { 0%, 10% { opacity: 0; } 3%, 7% { opacity: 1; } 11%, 100% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) {
  .flow-trail, .flow-node, .flow-node-highlight { animation: none; opacity: 0; }
}
</style>
