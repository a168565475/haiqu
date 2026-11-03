export type TubeFormulaGroup = 'ROUND' | 'RECTANGULAR' | 'OVAL'

export interface TubeCalculationFormula {
  id: string
  group_key: TubeFormulaGroup
  area_expression: string
  weight_expression: string
  updated_at: string
}

export type TubeFormulaInput = Pick<TubeCalculationFormula, 'area_expression' | 'weight_expression'>

export interface VersionedTubeFormula {
  data: TubeCalculationFormula
  etag: string
}
