/**
 * 转换-抽取管线 API：把格式适配器与字段抽取器的协作接口收敛到一处。
 * 通用 CRUD 仍走 backend-service.ts，本文件只放管线专属请求。
 */
import { request } from './client'

export type TargetFieldSpec = {
  source_field: string
  target_field: string
  type: string
  scale?: number | null
  nullable: boolean
}

export type CellStatus = 'converted' | 'missing' | 'rejected'

export type Cell = {
  line_no: number
  source_field: string
  target_field: string
  target_type: string
  status: CellStatus
  raw_value: unknown
  converted_value: unknown
  reason: string | null
  detail: string
  required: boolean
}

export type RejectedCell = Cell

export type ConversionRow = {
  line_no: number
  source_record: Record<string, unknown>
  converted_fields: Record<string, unknown>
  cells: Cell[]
  rejected_cells: RejectedCell[]
  missing_cells: Cell[]
  convert_ok: boolean
}

export type RejectionRef = {
  rejection_id: number
  line_no: number
  source_field: string
  target_field: string
  reason: string
  status: string
  fixed_batch_id?: number | null
}

export type ConversionBatch = {
  id: number
  source_name: string
  config_id: number | null
  target_schema: TargetFieldSpec[]
  total_rows: number
  bad_line_count: number
  rejected_row_count: number
  rejected_cell_count: number
  fully_converted_row_count: number
  rows: ConversionRow[]
  bad_lines: { line_no: number; raw_line: string; reason: string; detail: string }[]
  rejections: RejectionRef[]
  previous_batch_id?: number
}

export type ExtractionFieldStatus = 'delivered' | 'missing' | 'defaulted' | 'pending_fix'

export type ExtractionResult = {
  line_no: number
  template_id: number
  template_name: string
  source_path: string
  output_field: string
  status: ExtractionFieldStatus
  value: unknown
  detail: string
  reason?: string | null
  rejection_id: number | null
  source_field: string | null
  raw_value: unknown
  default_applied: boolean
}

export type ExtractionRun = {
  id: number
  template_id: number
  template_name: string
  batch_id: number
  total_rows: number
  delivered_count: number
  pending_fix_count: number
  missing_count: number
  defaulted_count: number
  results: ExtractionResult[]
}

export type Rejection = {
  id: number
  batch_id: number
  status: string
  line_no: number
  source_field: string
  target_field: string
  target_type: string
  raw_value: unknown
  reason: string
  detail: string
  source_record: Record<string, unknown>
  resolution: string | null
  fixed_batch_id: number | null
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(payload) })
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return (await response.json()) as T
}

export async function convertBatch(payload: {
  raw_text: string
  target_schema: TargetFieldSpec[]
  source_name: string
}): Promise<ConversionBatch> {
  return postJson('/api/pipeline/conversions', payload)
}

export async function resubmitBatch(
  batchId: number,
  payload: { raw_text: string },
): Promise<ConversionBatch> {
  return postJson(`/api/pipeline/conversions/${batchId}/resubmit`, payload)
}

export async function listConversions(): Promise<{ items: ConversionBatch[]; total: number }> {
  const response = await request('/api/pipeline/conversions')
  return (await response.json()) as { items: ConversionBatch[]; total: number }
}

export async function getConversion(batchId: number): Promise<ConversionBatch> {
  const response = await request(`/api/pipeline/conversions/${batchId}`)
  return (await response.json()) as ConversionBatch
}

export async function runExtraction(payload: {
  template_id: number
  batch_id: number
}): Promise<ExtractionRun> {
  return postJson('/api/pipeline/extractions', payload)
}

export async function listExtractions(): Promise<{ items: ExtractionRun[]; total: number }> {
  const response = await request('/api/pipeline/extractions')
  return (await response.json()) as { items: ExtractionRun[]; total: number }
}

export async function listRejections(onlyOpen = false): Promise<{ items: Rejection[] }> {
  const response = await request(`/api/pipeline/rejections?only_open=${onlyOpen}`)
  return (await response.json()) as { items: Rejection[] }
}

export async function getRejection(rejectionId: number): Promise<Rejection> {
  const response = await request(`/api/pipeline/rejections/${rejectionId}`)
  return (await response.json()) as Rejection
}
