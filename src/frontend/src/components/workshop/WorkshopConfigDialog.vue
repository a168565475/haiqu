<script setup lang="ts">
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'

withDefaults(defineProps<{
  title: string
  sectionLabel?: string
  fullscreen?: boolean
}>(), { fullscreen: true })

const visible = defineModel<boolean>({ required: true })
</script>

<template>
  <AppWindowDialog
    v-model="visible"
    :title="title"
    :width="fullscreen ? 1600 : 1100"
    :height="fullscreen ? 920 : 720"
    :fullscreen="fullscreen"
    destroy-on-close
    :class="{ 'workshop-manager-dialog': fullscreen }"
  >
    <template v-if="sectionLabel" #title>
      <div class="workshop-config-dialog__title">
        <span>{{ sectionLabel }}</span><i aria-hidden="true">/</i><strong>{{ title }}</strong>
      </div>
    </template>
    <slot />
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.workshop-config-dialog__title { display: flex; min-width: 0; align-items: center; gap: 8px; }
.workshop-config-dialog__title span { color: token.$crm-text-secondary; font-family: token.$crm-font-body; font-size: 13px; font-weight: 400; }
.workshop-config-dialog__title i { color: token.$crm-text-muted; font-style: normal; }
.workshop-config-dialog__title strong { overflow: hidden; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }

:global(.workshop-manager-dialog .app-window-dialog__body) { padding: 0; overflow: hidden; }
</style>
