<script setup lang="ts">
import { computed } from 'vue'
import type { AccessScope, CatalogEntry, Grant } from '@/types/access'
const props = defineProps<{ entry: CatalogEntry; grants: Grant[]; disabled?: boolean; preferTeam?: boolean }>()
const emit = defineEmits<{ change: [code: string, scopes: AccessScope[]]; configure: [code: string] }>()
const scopes = computed(() => props.grants.filter(g => g.permission === props.entry.code).map(g => g.scope).sort())
const joined = computed(() => scopes.value.join(','))
const restricted = computed(() => scopes.value.some(scope => scope === 'WORKSHOP' || scope === 'CRAFT'))
const choices = computed(() => [
  ['OWN', '本人'], ['TEAM', '所管团队'], ['OWN,TEAM', '本人及团队'], ['ALL', '全部'],
  ['MODULE', '按模块'], ['WORKSHOP', '指定车间'], ['CRAFT', '指定工艺'], ['STOCK', '库存来源'],
].filter(([value]) => value!.split(',').every(scope => props.entry.scopes.includes(scope as AccessScope))))
const custom = computed(() => joined.value && !choices.value.some(c => c[0] === joined.value))
function check(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  emit('change', props.entry.code, checked ? [props.entry.scopes.includes('MODULE') ? 'MODULE' : props.preferTeam ? 'TEAM' : 'OWN'] : [])
}
</script>
<template>
  <div class="permission-cell" :class="{ 'has-resource-scope': restricted }">
    <input type="checkbox" :aria-label="entry.label" :checked="scopes.length > 0" :disabled="disabled || !entry.available" @change="check">
    <select v-if="choices.length > 1" :class="{ 'restricted-select': restricted }" :aria-label="entry.label + '范围'" :value="joined || choices[0]?.[0]" :disabled="disabled || !scopes.length" @change="emit('change', entry.code, ($event.target as HTMLSelectElement).value.split(',') as AccessScope[])">
      <option v-for="choice in choices" :key="choice[0]" :value="choice[0]">{{ choice[1] }}</option>
      <option v-if="custom" :value="joined">已配置组合</option>
    </select>
    <button v-if="restricted" type="button" class="scope-configure" :aria-label="entry.label + '选择范围'" :disabled="disabled" @click="emit('configure', entry.code)">选</button>
  </div>
</template>
