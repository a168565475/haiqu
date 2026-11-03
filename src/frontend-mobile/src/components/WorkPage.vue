<script setup lang="ts">
import { useRouter } from 'vue-router'
import { NavBar as VanNavBar, Icon as VanIcon } from 'vant'
import 'vant/es/nav-bar/style'
defineProps<{ title: string; subtitle?: string; backTo?: string; home?: boolean }>()
const router = useRouter()
</script>

<template>
  <div class="work-page" :class="{ 'has-footer': $slots.footer }">
    <header v-show="!home" class="work-header" :class="{ 'is-home': home }">
      <van-nav-bar :border="false" :left-arrow="!home" @click-left="router.push(backTo || '/')">
        <template v-if="!home" #left><button class="back-button" aria-label="返回"><van-icon name="arrow-left" size="22" /></button></template>
        <template #title>
          <div class="work-title">
            <span v-if="home" class="work-brand" aria-hidden="true"><van-icon name="apps-o" size="23" /></span>
            <div class="work-heading"><h1>{{ title }}</h1><p v-if="subtitle">{{ subtitle }}</p></div>
          </div>
        </template>
        <template #right><slot name="header-action" /></template>
      </van-nav-bar>
    </header>
    <main class="work-content"><slot /></main>
    <footer v-if="$slots.footer" class="work-footer"><slot name="footer" /></footer>
  </div>
</template>
