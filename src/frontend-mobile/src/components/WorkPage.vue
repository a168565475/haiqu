<script setup lang="ts">
import { useRouter } from 'vue-router'
import { NavBar as VanNavBar, Icon as VanIcon } from 'vant'
import 'vant/es/nav-bar/style'
import WorkshopMenu from '@/components/WorkshopMenu.vue'
defineProps<{ title: string; subtitle?: string; backTo?: string; home?: boolean; section?: 'issue' | 'report' | 'receipt' | 'configuration' }>()
const router = useRouter()
</script>

<template>
  <div class="work-page" :class="{ 'has-footer': $slots.footer }">
    <header v-show="!home || section" class="work-header" :class="{ 'is-home': home, 'has-navigation': section }">
      <van-nav-bar :border="false" :left-arrow="false">
        <template #left><WorkshopMenu v-if="section && home" :active="section" /><button v-else-if="!home" class="back-button" aria-label="返回" @click="router.push(backTo || '/')"><van-icon name="arrow-left" size="22" /></button></template>
        <template #title>
          <div class="work-title">
            <span v-if="home && !section" class="work-brand" aria-hidden="true"><van-icon name="apps-o" size="23" /></span>
            <div class="work-heading"><h1>{{ title }}</h1><p v-if="subtitle">{{ subtitle }}</p></div>
          </div>
        </template>
        <template #right><WorkshopMenu v-if="section && !home" :active="section" /><slot name="header-action" /></template>
      </van-nav-bar>
    </header>
    <main class="work-content"><slot /></main>
    <footer v-if="$slots.footer" class="work-footer"><slot name="footer" /></footer>
  </div>
</template>

<style scoped>
.work-header.has-navigation { --van-nav-bar-height: 64px; }
.work-header.has-navigation :deep(.van-nav-bar__title) { margin-left: 56px; margin-right: 56px; }
</style>
