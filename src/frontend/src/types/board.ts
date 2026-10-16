export interface BoardMetric {
  label: string
  value: string | number
  tone: 'blue' | 'green' | 'yellow' | 'red'
  comparison?: string
}

export interface BoardColumn {
  key: string
  label: string
  width?: string
  tone?: string
}

export type BoardRow = Record<string, string | number>

export interface BoardProcess {
  label: string
  completed: number
  total: number
}

export interface BoardOrder {
  id: string
  productCode: string
  product: string
  specification: string
  planned: number
  priority: string
  processes: BoardProcess[]
}
