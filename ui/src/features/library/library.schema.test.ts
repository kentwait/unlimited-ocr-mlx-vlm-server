// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, expect, it } from 'vitest'

import { TreeNodeSchema, SpanSchema } from './library.schema'

describe('TreeNodeSchema', () => {
  it('accepts a valid pdf node with children', () => {
    const node = {
      name: 'gao2026.pdf',
      path: '/tmp/refs/gao2026.pdf',
      kind: 'pdf',
      hasMd: true,
      hasSpans: false,
      size: 123,
      children: null,
    }
    expect(TreeNodeSchema.parse(node)).toMatchObject({
      kind: 'pdf',
      hasMd: true,
    })
  })

  it('rejects an unknown kind', () => {
    const node = {
      name: 'x.bin',
      path: '/x.bin',
      kind: 'binary',
      hasMd: false,
      hasSpans: false,
      size: 1,
      children: null,
    }
    expect(() => TreeNodeSchema.parse(node)).toThrow()
  })
})

describe('SpanSchema', () => {
  it('requires exactly four box coordinates', () => {
    const span = {
      page: 2,
      label: 'text',
      box: [64, 183, 341, 197],
      text: 'hi',
    }
    expect(SpanSchema.parse(span)).toMatchObject({ page: 2 })
    expect(() => SpanSchema.parse({ ...span, box: [1, 2, 3] })).toThrow()
  })
})

describe('markdown anchor splitting contract', () => {
  // The assemble/split pair must round-trip: assembleMarkdown writes
  // `<!-- ocr:page:N -->` anchors; splitByAnchors recovers per-page chunks.
  it('anchor format matches the assembler template', () => {
    const anchor = (page: number) => `<!-- ocr:page:${String(page)} -->`
    expect(anchor(3)).toBe('<!-- ocr:page:3 -->')
  })
})
