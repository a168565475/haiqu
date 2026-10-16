import type { ObjectDirective } from 'vue'

type OverflowObserver = {
  refresh: () => void
  disconnect: () => void
}

const observers = new WeakMap<HTMLElement, OverflowObserver>()

// 原生表格只在实际横向溢出时启用操作列定位，同时响应容器和列宽变化。
export const vHorizontalOverflow: ObjectDirective<HTMLElement> = {
  mounted(element) {
    let table: HTMLTableElement | null = null
    const measure = () => {
      element.dataset.horizontalOverflow = String(element.clientWidth > 0 && element.scrollWidth > element.clientWidth)
    }
    const observer = new ResizeObserver(measure)
    const refresh = () => {
      const currentTable = element.querySelector('table')
      if (currentTable !== table) {
        if (table) observer.unobserve(table)
        table = currentTable
        if (table) observer.observe(table)
      }
      measure()
    }
    observer.observe(element)
    observers.set(element, { refresh, disconnect: () => observer.disconnect() })
    refresh()
  },
  updated(element) {
    observers.get(element)?.refresh()
  },
  unmounted(element) {
    observers.get(element)?.disconnect()
    observers.delete(element)
    delete element.dataset.horizontalOverflow
  },
}
