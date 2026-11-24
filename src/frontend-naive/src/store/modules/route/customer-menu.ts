/** 菜单分组不注册路由，真实页面继续使用原路径与权限过滤结果。 */
export function groupCustomerMenus(
  menus: App.Global.Menu[],
  translate: (key: App.I18n.I18nKey) => string
): App.Global.Menu[] {
  const routeKeys = ['customers', 'complaints', 'inquiries'];
  const firstIndex = menus.findIndex(menu => routeKeys.includes(menu.key));
  if (firstIndex === -1) return [...menus];

  const liveMenus = routeKeys.flatMap(key => {
    const menu = menus.find(item => item.key === key);
    return menu ? [menu] : [];
  });
  const pendingKeys = ['quotation', 'salesOrders', 'tasks', 'analytics'] as const;
  const pendingMenus: App.Global.Menu[] = pendingKeys.map(key => {
    const i18nKey = `customerMenu.${key}` as const;
    return { key: `customer-management-${key}`, label: translate(i18nKey), i18nKey, disabled: true };
  });
  const group: App.Global.Menu = {
    key: 'customer-management',
    label: translate('customerMenu.title'),
    i18nKey: 'customerMenu.title',
    icon: liveMenus[0].icon,
    children: [...liveMenus, ...pendingMenus]
  };
  const result = menus.filter(menu => !routeKeys.includes(menu.key));
  result.splice(firstIndex, 0, group);
  return result;
}
