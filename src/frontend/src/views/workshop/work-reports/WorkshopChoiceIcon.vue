<script setup lang="ts">
defineProps<{ name: string; active: boolean }>()
</script>

<template>
  <svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" class="workshop-choice-icon" :class="{ 'is-active': active }">
    <g v-if="name === '金工车间'">
      <path d="M8 54h48M13 53V13a3 3 0 0 1 3-3h29v11H20v32" />
      <path class="icon-muted" d="M14 14h7v34h-7z" />
      <rect x="27" y="45" width="26" height="5" rx="1" class="icon-accent" />
      <g class="icon-drill"><path class="icon-accent" d="M32 22h14v10H32z" /><path d="M36 33v5l3 5 3-5v-5M37 36h4" /></g>
      <g class="icon-sparks icon-accent"><path d="m49 37 4-3m-3 8h5m-9-11 1-4" /></g>
      <circle cx="27" cy="15.5" r="1.5" />
    </g>
    <g v-else-if="name === '车缝车间'">
      <path class="icon-muted" d="M9 22a5 5 0 0 1 5-5h30a5 5 0 0 1 5 5v22H34V30H21v5H9z" />
      <path d="M8 48h48v6H8zM36 43h13M27 18v-6h8v6" />
      <circle cx="51" cy="25" r="5" class="icon-accent" />
      <circle cx="51" cy="25" r="1" />
      <g class="icon-needle"><path class="icon-accent" d="M16 33v12m-3-8h6" /></g>
      <path class="icon-fabric icon-accent" d="M11 46h22m-19 4h2m4 0h2m4 0h2" />
      <path d="M39 24h3" />
    </g>
    <g v-else-if="name === '装配车间'">
      <path d="M7 47h50v6H7zM12 53v5m40-5v5M13 43h38" />
      <g class="icon-gear-main">
        <path class="icon-accent" d="m20 10 6 0 1 5 4 2 4-2 4 5-3 4 1 4 4 2-1 6-5 0-3 3 0 5-6 2-2-4-4-1-4 3-5-4 2-4-1-4-4-2 1-6 5-1 2-3z" />
        <circle cx="25" cy="27" r="6" />
      </g>
      <g class="icon-gear-small">
        <path class="icon-muted" d="m46 8 4 1 0 3 3 2 3-1 2 4-2 2 0 3 2 2-2 4-3-1-3 2-1 3-4-1 0-3-3-2-3 1-2-4 2-2 0-3-2-2 2-4 3 1 3-2z" />
        <circle cx="47" cy="20" r="4" />
      </g>
    </g>
    <g v-else-if="name === '敲布孔'">
      <path d="M9 55h46M13 54V13h34v10H24v25" />
      <path class="icon-muted" d="M14 16h6v32h-6z" />
      <path d="M35 12V7h10M43 7h8" />
      <g class="icon-punch"><path class="icon-accent" d="M30 25h15v9H30z" /><path d="M35 34v9h5v-9" /></g>
      <path class="icon-accent" d="M25 49h28v5H25z" />
      <ellipse class="icon-punch-ring icon-accent" cx="38" cy="48" rx="5" ry="2" />
    </g>
  </svg>
</template>

<style scoped>
.workshop-choice-icon { width: 52px; height: 52px; flex: none; color: currentColor; }
.icon-accent { color: var(--erp-color-brand); fill: color-mix(in srgb, var(--erp-color-brand) 12%, var(--erp-color-surface)); }
.icon-muted { fill: var(--erp-color-subtle); }
.icon-drill, .icon-needle, .icon-fabric, .icon-punch, .icon-gear-main, .icon-gear-small, .icon-punch-ring { transform-box: fill-box; transform-origin: center; }
.is-active .icon-drill, .is-active .icon-punch { animation: workshop-tool-stroke 720ms ease-in-out 2; }
.is-active .icon-needle { animation: workshop-needle-stroke 340ms ease-in-out 2; }
.is-active .icon-fabric { animation: workshop-fabric-feed 680ms ease-out 2; }
.is-active .icon-gear-main { animation: workshop-gear-turn 1000ms ease-in-out 2; }
.is-active .icon-gear-small { animation: workshop-gear-turn 1000ms ease-in-out 2 reverse; }
.is-active .icon-sparks, .is-active .icon-punch-ring { animation: workshop-tool-pulse 720ms ease-in-out 2; }
@keyframes workshop-tool-stroke { 0%, 100% { transform: translateY(0); } 45%, 60% { transform: translateY(3px); } }
@keyframes workshop-needle-stroke { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(3px); } }
@keyframes workshop-fabric-feed { 0%, 100% { transform: translateX(0); } 60% { transform: translateX(2px); } }
@keyframes workshop-gear-turn { 0% { transform: rotate(0deg); } 65%, 100% { transform: rotate(30deg); } }
@keyframes workshop-tool-pulse { 0%, 100% { opacity: .4; } 50%, 70% { opacity: 1; } }
@media (max-width: 760px) { .workshop-choice-icon { width: 42px; height: 42px; } }
@media (prefers-reduced-motion: reduce) { .workshop-choice-icon * { animation: none !important; } }
@media print { .workshop-choice-icon * { animation: none !important; } }
</style>
