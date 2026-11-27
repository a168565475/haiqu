const tableInput = 'input.el-input__inner:not([readonly]):not(:disabled), input.el-input__inner[data-table-focus]:not(:disabled)'

export function focusTableInputBelow(event: KeyboardEvent): void {
  if (event.isComposing || event.keyCode === 229 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  const current = event.target
  if (!(current instanceof HTMLInputElement) || !current.matches(tableInput)) return
  const cell = current.closest('td')
  if (!cell) return

  for (let row = cell.parentElement?.nextElementSibling; row instanceof HTMLTableRowElement; row = row.nextElementSibling) {
    const next = row.cells[cell.cellIndex]?.querySelector<HTMLInputElement>(tableInput)
    if (next) {
      event.preventDefault()
      next.focus()
      return
    }
  }
}
