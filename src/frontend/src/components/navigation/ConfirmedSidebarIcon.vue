<script setup lang="ts">
defineProps<{ name: string }>()
</script>

<template>
  <svg
    class="confirmed-sidebar-icon"
    :data-confirmed-sidebar-icon="name"
    viewBox="0 0 48 48"
    width="100%"
    height="100%"
    fill="none"
    stroke-width="2.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <g v-if="name === 'workbench'">
      <rect class="icon-accent-fill icon-accent-stroke" x="7" y="7" width="14" height="14" rx="2.5" />
      <rect class="icon-muted" x="27" y="7" width="14" height="14" rx="2.5" />
      <rect class="icon-muted" x="7" y="27" width="14" height="14" rx="2.5" />
      <rect class="icon-muted" x="27" y="27" width="14" height="14" rx="2.5" />
    </g>

    <g v-else-if="name === 'finance-management'" class="finance-primary-icon">
      <rect x="6" y="5" width="29" height="38" rx="4" class="icon-muted finance-ledger"/>
      <path d="M14 14h13M14 21h8M14 28h6" class="finance-ledger-lines"/>
      <circle cx="34" cy="32" r="10" class="icon-accent-stroke finance-coin"/>
      <path d="m29 27 5 6 5-6m-5 6v5m-5-5h10m-9 4h8" class="icon-accent-stroke"/>
    </g>

    <g v-else-if="name === 'customer-management'">
      <path class="icon-muted" d="M30 10.5c4-2.5 10 .1 10 5.5 0 4-2.8 7-6.5 7.5C41 25 44 31 44 38h-4" />
      <circle class="icon-warm" cx="17" cy="17" r="7.5" />
      <path class="icon-warm" d="M4 38c0-8.5 5.8-13 13-13s13 4.5 13 13Z" />
    </g>

    <g v-else-if="name === 'sample-management'">
      <path class="icon-muted" d="m38 11 7 3.5c1 .5 1.2 1.5.7 2.5L35.5 42c-.5 1-1.5 1.4-2.5.9l-3-1.4" />
      <rect class="icon-muted" x="20" y="5" width="14" height="33" rx="2.5" transform="rotate(2 27 21.5)" />
      <circle class="icon-cutout" cx="27" cy="31" r="2.4" />
      <g transform="rotate(-24 16 27)">
        <rect class="icon-accent-fill" x="9" y="12" width="14" height="30" rx="2" />
        <circle class="icon-cutout" cx="16" cy="35" r="2.5" />
      </g>
    </g>

    <g v-else-if="name === 'product-management'">
      <path d="M5 14 24 4l19 10v20.5c0 1-.5 1.8-1.4 2.3L25.5 45a3 3 0 0 1-3 0L6.4 36.8C5.5 36.3 5 35.5 5 34.5Z" />
      <path class="icon-accent-fill icon-no-stroke" d="M12 17.7v5.8l4 2.1v-5.8L35 9.8l-4.4-2.3Z" />
      <path d="m5 14 19 10 19-10M24 24v21" />
    </g>

    <g v-else-if="name === 'production-management'">
      <path class="icon-muted" d="M3 43V24h4.5L9 5h7l1 17 14-9v9l14-9v30Z" />
      <rect class="icon-accent-fill icon-no-stroke" x="11" y="30" width="5.5" height="6.5" rx="1" />
      <rect class="icon-accent-fill icon-no-stroke" x="21.5" y="30" width="5.5" height="6.5" rx="1" />
      <rect class="icon-accent-fill icon-no-stroke" x="32" y="30" width="5.5" height="6.5" rx="1" />
    </g>

    <g v-else-if="name === 'procurement-management'">
      <rect class="icon-accent-fill icon-no-stroke" x="23" y="3" width="15" height="11" rx="1.5" />
      <path class="icon-cutout" d="M29 3h3v11h-3Z" />
      <path class="icon-muted" d="M12 16h34l-3.8 15.2A4 4 0 0 1 38.3 34H17.5a4 4 0 0 1-4-3.3Z" />
      <path d="M2 8h5a3 3 0 0 1 3 2.5l3.5 20.2" />
      <circle class="icon-muted" cx="16" cy="41" r="3" />
      <circle class="icon-muted" cx="38" cy="41" r="3" />
    </g>

    <g v-else-if="name === 'workshop-management'">
      <rect class="icon-muted" x="18" y="3" width="16" height="5" />
      <rect class="icon-muted icon-no-stroke" x="10" y="8" width="24" height="11" />
      <path d="M10 26V8h24v11H18" />
      <path class="icon-muted" d="M23 19v6h6v-6" />
      <path class="icon-accent-stroke" d="M26 25v4" />
      <path class="icon-muted" d="M5 39v6h6v-6m27 0v6h6v-6" />
      <path class="icon-muted" d="M5 33h39v7H5Z" />
      <path class="icon-accent-stroke" d="M21 33h10" />
    </g>

    <g v-else-if="name === 'warehouse-management'">
      <path class="icon-accent-stroke" d="M13 29h22M13 35h22M13 41h22" />
      <path class="icon-muted" d="M3 43V17L24 5l21 12v26h-9V22H12v21Z" />
    </g>

    <g v-else-if="name === 'employee-management'">
      <circle class="icon-warm" cx="16" cy="13" r="7" />
      <path class="icon-warm" d="M3 38v-5c0-7 5-11 13-11 4 0 7 1 10 4" />
      <rect class="icon-muted" x="25" y="23" width="19" height="20" rx="3" />
      <path class="icon-accent-stroke" d="M30 20v6m9-6v6m-14 5h19m-13 5 3 3 5-5" />
    </g>

    <g v-else-if="name === 'boards'">
      <path d="m14 42 9-9m2 0 9 9" />
      <rect x="5" y="8" width="38" height="26" rx=".7" />
      <rect class="icon-ink-fill icon-no-stroke" x="12.5" y="22" width="5" height="8" rx="1.2" opacity=".76" />
      <rect class="icon-accent-fill icon-no-stroke" x="21.5" y="17" width="5" height="13" rx="1.2" />
      <rect class="icon-ink-fill icon-no-stroke" x="30.5" y="13" width="5" height="17" rx="1.2" />
    </g>

    <g v-else-if="name === 'access-management'">
      <path d="m24 4 16 7v11c0 10-6.5 17-16 22C14.5 39 8 32 8 22V11Z" />
      <path class="icon-accent-stroke" d="m18 24 5 5 10-11" />
    </g>

    <g v-else-if="name === 'settings'">
      <path d="M6 12h5m14 0h17M6 24h21m14 0h1M6 36h5m14 0h17" />
      <circle class="icon-accent-fill icon-no-stroke" cx="17.5" cy="12" r="5" />
      <circle class="icon-ink-fill icon-no-stroke" cx="33" cy="24" r="5" />
      <circle class="icon-ink-fill icon-no-stroke" cx="17.5" cy="36" r="5" opacity=".84" />
    </g>

    <g v-else-if="name === 'theme-settings'">
      <path d="M25 5C13 5 5 14 5 25c0 10 6 17 14 17 4 0 6-3 4.5-7-1.5-4 2.5-8 6.5-6 5.5 3 12 1 13-5C45 14 36 5 25 5Z" />
      <circle class="icon-accent-fill icon-no-stroke" cx="25" cy="14" r="4.2" />
      <circle class="icon-ink-fill icon-no-stroke" cx="15" cy="22" r="4.2" opacity=".45" />
      <circle class="icon-ink-fill icon-no-stroke" cx="35" cy="19" r="3.4" opacity=".45" />
    </g>
  </svg>
</template>

<style scoped>
.confirmed-sidebar-icon {
  display: block;
  width: 100%;
  height: 100%;
  flex: none;
  stroke: var(--sidebar-icon-ink, #283133);
}

.icon-ink-fill {
  fill: var(--sidebar-icon-ink, #283133);
}

.icon-accent-fill {
  fill: var(--sidebar-icon-accent, #c84e28);
}

.icon-accent-stroke {
  stroke: var(--sidebar-icon-accent, #c84e28);
}

.icon-warm {
  fill: var(--sidebar-icon-fill, #e89269);
}

.icon-muted {
  fill: var(--sidebar-icon-muted, #e3e5e1);
}

.icon-cutout {
  fill: #fafaf7;
  stroke: none;
}

.icon-no-stroke {
  stroke: none;
}
.finance-coin { fill: var(--erp-menu-selected-background); }
:global(.app-sidebar__menu-item.is-active) .finance-ledger { fill: var(--erp-menu-accent); }
:global(.app-sidebar__menu-item.is-active) .finance-ledger-lines { stroke: var(--erp-menu-icon-selected-muted); }
:global(.app-sidebar__menu-item.is-active) .finance-coin { fill: var(--erp-menu-icon-selected-muted); }
</style>
