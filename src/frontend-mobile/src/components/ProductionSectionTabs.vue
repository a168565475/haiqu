<script setup lang="ts">
defineProps<{ section: 'issue' | 'report'; records: boolean }>()
</script>

<template>
  <nav class="production-section-tabs" :aria-label="section === 'issue' ? '生产领料页面' : '生产报工页面'">
    <RouterLink :to="section === 'issue' ? '/' : '/production-report'" :aria-current="!records ? 'page' : undefined">{{ section === 'issue' ? '生产领料' : '生产报工' }}</RouterLink>
    <RouterLink :to="section === 'issue' ? '/issue-records' : '/production-report?view=records'" :aria-current="records ? 'page' : undefined">{{ section === 'issue' ? '领料记录' : '报工记录' }}</RouterLink>
  </nav>
</template>

<style scoped>
.production-section-tabs { display: flex; gap: 24px; margin-bottom: 12px; border-bottom: 1px solid var(--mobile-border); }
.production-section-tabs a { display: grid; place-items: center; min-height: 48px; padding: 0 4px; border-bottom: 2px solid transparent; color: var(--mobile-muted); font-size: 16px; text-decoration: none; }
.production-section-tabs a[aria-current="page"] { border-bottom-color: var(--mobile-primary); color: var(--mobile-primary); font-weight: 600; }
.production-section-tabs a:focus-visible { outline: 2px solid var(--mobile-primary); outline-offset: -2px; }
</style>
