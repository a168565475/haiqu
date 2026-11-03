<template>
  <main class="account-transition" aria-labelledby="account-transition-title">
    <h1 id="account-transition-title">身份操作安全页</h1>
    <p>此页不载入业务单据。请查看上方的当前身份与操作结果，切换和返回均不会自动重试。</p>
    <p>若操作已取消，请先核对当前身份，再主动进入首页或重新发起操作。</p>
    <RouterLink class="account-transition__home" :to="{ name: 'home', query: {}, hash: '' }">进入首页</RouterLink>
  </main>
</template>

<style scoped lang="scss">
.account-transition {
  box-sizing: border-box;
  width: min(100%, 720px);
  margin: 0 auto;
  padding: 48px 24px;
  color: var(--erp-color-text-primary);
  font-family: var(--erp-font-body, 'Noto Sans SC', 'Microsoft YaHei', sans-serif);
  line-height: 1.7;

  h1 { margin: 0 0 20px; font-size: 22px; font-weight: 600; }
  p { margin: 0 0 12px; overflow-wrap: anywhere; }
}
.account-transition__home {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  margin-top: 12px;
  color: var(--erp-color-brand);
  text-underline-offset: 3px;
  &:focus-visible { outline: 2px solid var(--erp-color-brand); outline-offset: 3px; border-radius: 5px; }
}
</style>
