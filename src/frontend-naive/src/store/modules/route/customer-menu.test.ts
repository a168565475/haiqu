import assert from 'node:assert/strict';
import { test } from 'node:test';
import { groupCustomerMenus } from './customer-menu';

const labels: Record<string, string> = {
  'customerMenu.title': '客户管理',
  'customerMenu.quotation': '报价管理（待接入）',
  'customerMenu.salesOrders': '销售订单（待接入）',
  'customerMenu.tasks': '任务中心（待接入）',
  'customerMenu.analytics': '分析中心（待接入）'
};

function routeMenu(key: string, label = key): App.Global.Menu {
  return {
    key,
    label,
    routeKey: key as App.Global.Menu['routeKey'],
    routePath: `/${key}` as App.Global.Menu['routePath']
  };
}

test('客户管理保留真实路由并按七项固定顺序显示', () => {
  const menus = [
    routeMenu('home'), routeMenu('inquiries', '询盘管理'),
    routeMenu('complaints', '客诉管理'), routeMenu('customers', '客户列表')
  ];
  const result = groupCustomerMenus(menus, key => labels[key]);
  assert.deepEqual(result.map(menu => menu.key), ['home', 'customer-management']);
  const group = result[1];
  assert.equal(group.label, '客户管理');
  assert.equal(group.routeKey, undefined);
  assert.equal(group.routePath, undefined);
  assert.deepEqual(group.children?.map(menu => menu.label), [
    '客户列表', '客诉管理', '询盘管理', '报价管理（待接入）',
    '销售订单（待接入）', '任务中心（待接入）', '分析中心（待接入）'
  ]);
  assert.deepEqual(group.children?.slice(0, 3).map(menu => menu.routePath), ['/customers', '/complaints', '/inquiries']);
  assert.equal(group.children?.[2].disabled, undefined);
});

test('四个待接入菜单禁用且不产生路由', () => {
  const [group] = groupCustomerMenus(
    [routeMenu('customers'), routeMenu('complaints'), routeMenu('inquiries')], key => labels[key]
  );
  const pending = group.children!.slice(3);
  assert.equal(pending.length, 4);
  assert.equal(group.children!.filter(menu => menu.disabled).length, 4);
  pending.forEach(menu => {
    assert.equal(menu.disabled, true);
    assert.equal(menu.routeKey, undefined);
    assert.equal(menu.routePath, undefined);
    assert.match(menu.label, /待接入/);
  });
});

test('不修改入参，也不凭空补出无权限或不存在的真实路由', () => {
  const menus = [routeMenu('home'), routeMenu('customers')];
  const before = structuredClone(menus);
  menus.forEach(Object.freeze);
  Object.freeze(menus);
  const result = groupCustomerMenus(menus, key => labels[key]);
  assert.deepEqual(menus, before);
  assert.equal(result[1].children?.some(menu => menu.key === 'complaints'), false);
  assert.equal(result[1].children?.some(menu => menu.key === 'inquiries'), false);
  assert.deepEqual(groupCustomerMenus([menus[0]], key => labels[key]), [menus[0]]);
});
