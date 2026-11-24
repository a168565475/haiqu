import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import type { RouteKey } from '@elegant-router/types';
import { useContext } from '@sa/hooks';
import { useRouteStore } from '@/store/modules/route';
import { useThemeStore } from '@/store/modules/theme';
import { useRouterPush } from '@/hooks/common/router';

export const [provideMixMenuContext, useMixMenuContext] = useContext(
  {
    name: 'MixMenu',
    key: Symbol.for('MixMenu')
  },
  useMixMenu
);

function useMixMenu() {
  const route = useRoute();
  const routeStore = useRouteStore();
  const themeStore = useThemeStore();
  const { selectedKey } = useMenu();
  const { routerPushByKeyWithMetaQuery } = useRouterPush();

  const allMenus = computed<App.Global.Menu[]>(() => routeStore.menus);

  const firstLevelMenus = computed<App.Global.Menu[]>(() =>
    routeStore.menus.map(menu => {
      const { children: _, ...rest } = menu;

      return rest;
    })
  );

  const activeFirstLevelMenuKey = ref('');

  function setActiveFirstLevelMenuKey(key: string) {
    activeFirstLevelMenuKey.value = key;
  }

  function getActiveFirstLevelMenuKey() {
    const [firstLevelMenuKey] = routeStore.getSelectedMenuKeyPath(selectedKey.value);
    setActiveFirstLevelMenuKey(firstLevelMenuKey || '');
  }

  const isActiveFirstLevelMenuHasChildren = computed(() => {
    if (!activeFirstLevelMenuKey.value) {
      return false;
    }

    const findItem = allMenus.value.find(item => item.key === activeFirstLevelMenuKey.value);

    return Boolean(findItem?.children?.length);
  });

  function handleSelectFirstLevelMenu(key: string) {
    const menu = allMenus.value.find(item => item.key === key);
    if (!menu || menu.disabled) return;
    setActiveFirstLevelMenuKey(key);

    if (!isActiveFirstLevelMenuHasChildren.value && menu.routeKey) {
      routerPushByKeyWithMetaQuery(menu.routeKey);
    }
  }

  const secondLevelMenus = computed<App.Global.Menu[]>(
    () => allMenus.value.find(menu => menu.key === activeFirstLevelMenuKey.value)?.children || []
  );

  const activeSecondLevelMenuKey = ref('');

  function setActiveSecondLevelMenuKey(key: string) {
    activeSecondLevelMenuKey.value = key;
  }

  function getActiveSecondLevelMenuKey() {
    const [, secondLevelMenuKey] = routeStore.getSelectedMenuKeyPath(selectedKey.value);
    setActiveSecondLevelMenuKey(secondLevelMenuKey || '');
  }

  const isActiveSecondLevelMenuHasChildren = computed(() => {
    if (!activeSecondLevelMenuKey.value) {
      return false;
    }

    const findItem = secondLevelMenus.value.find(item => item.key === activeSecondLevelMenuKey.value);

    return Boolean(findItem?.children?.length);
  });

  function handleSelectSecondLevelMenu(key: string) {
    const menu = secondLevelMenus.value.find(item => item.key === key);
    if (!menu || menu.disabled) return;
    setActiveSecondLevelMenuKey(key);

    if (!isActiveSecondLevelMenuHasChildren.value && menu.routeKey) {
      routerPushByKeyWithMetaQuery(menu.routeKey);
    }
  }

  const childLevelMenus = computed<App.Global.Menu[]>(
    () => secondLevelMenus.value.find(menu => menu.key === activeSecondLevelMenuKey.value)?.children || []
  );

  const hasChildLevelMenus = computed(() => childLevelMenus.value.length > 0);

  function getDeepestLevelMenuKey(): RouteKey | null {
    const firstLevelMenu = allMenus.value.find(menu => menu.key === activeFirstLevelMenuKey.value);
    // 纯菜单分组只展开，不受自动打开首个子菜单设置影响。
    if (!firstLevelMenu?.routeKey || !themeStore.sider.autoSelectFirstMenu) {
      return null;
    }

    function findDeepest(menu: App.Global.Menu): RouteKey | null {
      if (menu.disabled) return null;
      if (!menu.children?.length) {
        return menu.routeKey || null;
      }

      return menu.children.map(findDeepest).find(Boolean) || null;
    }

    return secondLevelMenus.value.map(findDeepest).find(Boolean) || null;
  }

  function activeDeepestLevelMenuKey() {
    const deepestLevelMenuKey = getDeepestLevelMenuKey();
    if (!deepestLevelMenuKey) return;

    routerPushByKeyWithMetaQuery(deepestLevelMenuKey);
  }

  watch(
    () => route.name,
    () => {
      getActiveFirstLevelMenuKey();
      getActiveSecondLevelMenuKey();
    },
    { immediate: true }
  );

  return {
    firstLevelMenus,
    activeFirstLevelMenuKey,
    setActiveFirstLevelMenuKey,
    isActiveFirstLevelMenuHasChildren,
    handleSelectFirstLevelMenu,
    getActiveFirstLevelMenuKey,
    secondLevelMenus,
    activeSecondLevelMenuKey,
    setActiveSecondLevelMenuKey,
    isActiveSecondLevelMenuHasChildren,
    handleSelectSecondLevelMenu,
    getActiveSecondLevelMenuKey,
    childLevelMenus,
    hasChildLevelMenus,
    getDeepestLevelMenuKey,
    activeDeepestLevelMenuKey
  };
}

export function useMenu() {
  const route = useRoute();

  const selectedKey = computed(() => {
    const { hideInMenu, activeMenu } = route.meta;
    const name = route.name as string;

    const routeName = (hideInMenu ? activeMenu : name) || name;

    return routeName;
  });

  return {
    selectedKey
  };
}
