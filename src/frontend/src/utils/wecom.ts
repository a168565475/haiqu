// 只用于选择界面与登录入口，成员身份和权限仍由后端校验。
export function isWeComBrowser(userAgent = navigator.userAgent): boolean {
  return /\bwxwork\//i.test(userAgent)
}
