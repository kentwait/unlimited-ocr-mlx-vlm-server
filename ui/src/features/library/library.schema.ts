import { z } from 'zod'

/**
 * Client-safe contracts for the library feature: Tauri command payloads,
 * OCR-server responses, and the markdown/span artifacts the app writes.
 * The Rust command layer (src-tauri) and the OCR server are the "server"
 * side of this feature; every response crossing into the app is validated
 * here before use.
 */

export const TreeNodeSchema: z.ZodType<TreeNode> = z.lazy(() =>
  z.object({
    name: z.string(),
    path: z.string(),
    kind: z.enum(['dir', 'pdf', 'md', 'jsonl', 'other']),
    hasMd: z.boolean(),
    hasSpans: z.boolean(),
    size: z.number(),
    children: z.array(TreeNodeSchema).nullable(),
  }),
)

export type TreeNode = {
  name: string
  path: string
  kind: 'dir' | 'pdf' | 'md' | 'jsonl' | 'other'
  hasMd: boolean
  hasSpans: boolean
  size: number
  children: TreeNode[] | null
}

export const ServerHealthSchema = z.object({
  status: z.enum(['ok', 'loading']),
  engine: z.enum(['real', 'fake']),
  model_loaded: z.boolean(),
  model_ref: z.string().nullable().optional(),
  device: z.string(),
})

export type ServerHealth = z.infer<typeof ServerHealthSchema>

export const SpanSchema = z.object({
  page: z.number().int(),
  label: z.string(),
  box: z.array(z.number()).length(4), // [x1, y1, x2, y2] normalized 0-1000
  text: z.string(),
})

export type Span = z.infer<typeof SpanSchema>

export const PageResultSchema = z.object({
  page: z.number().int(),
  markdown: z.string(),
  elapsed_s: z.number(),
  tokens: z.number().nullable().optional(),
  tps: z.number().nullable().optional(),
  peak_memory_gb: z.number().nullable().optional(),
  early_stop: z.boolean().optional(),
  cleanup_method: z.string().nullable().optional(),
  cleanup_elapsed_s: z.number().nullable().optional(),
  corrections: z.record(z.string(), z.unknown()).nullable().optional(),
  spans_jsonl: z.string().nullable().optional(),
})

export type PageResult = z.infer<typeof PageResultSchema>

export const DocumentParseResponseSchema = z.object({
  kind: z.enum(['pdf', 'image']),
  n_pages: z.number().int(),
  results: z.array(PageResultSchema),
  total_elapsed_s: z.number(),
  furniture: z
    .object({
      template: z.string().nullable(),
      removed_total: z.number(),
      removed_by_page: z.record(z.string(), z.number()),
      samples: z.array(z.unknown()),
    })
    .nullable()
    .optional(),
})

export type DocumentParseResponse = z.infer<typeof DocumentParseResponseSchema>

export const ParseJobStatusSchema = z.object({
  job_id: z.string(),
  status: z.enum(['pending', 'running', 'done', 'error']),
  kind: z.string().nullable().optional(),
  filename: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
  result: DocumentParseResponseSchema.nullable().optional(),
  created_at: z.number(),
  started_at: z.number().nullable().optional(),
  finished_at: z.number().nullable().optional(),
  phase: z.enum(['ocr', 'cleanup']).nullable().optional(),
  pages_done: z.number().optional(),
  pages_total: z.number().nullable().optional(),
})

export type ParseJobStatus = z.infer<typeof ParseJobStatusSchema>

/** One page's markdown, split from the assembled document by its anchor. */
export type MarkdownChunk = {
  page: number
  content: string
}

/**
 * Section-level focus request: scroll the markdown pane to the block
 * matching `snippet` on `page`. `nonce` re-triggers repeat selections.
 */
export type FocusSpan = {
  page: number
  snippet: string
  nonce: number
}

/** Parse options the UI exposes (mirrors the OCR server's form fields). */
export type ParseOptions = {
  dpi: number
  pages: string
  furniture: 'auto' | 'none' | 'nature' | 'science' | 'pmc'
  ocrModel: 'default' | 'bf16'
}
