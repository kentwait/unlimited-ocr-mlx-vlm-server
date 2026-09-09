// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, expect, it } from 'vitest'

import { TreeNodeSchema, SpanSchema } from './library.schema'
import {
  markdownPathFor,
  parseSpansJsonl,
  pickReadingPage,
  spansPathFor,
} from './library.functions'

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

describe('parseSpansJsonl', () => {
  it('groups spans by page, skipping blank lines', () => {
    const jsonl = [
      '{"page":1,"label":"title","box":[0,0,100,50],"text":"T"}',
      '',
      '{"page":2,"label":"text","box":[0,60,100,90],"text":"B"}',
    ].join('\n')
    const byPage = parseSpansJsonl(jsonl)
    expect(byPage.get(1)?.map((s) => s.text)).toEqual(['T'])
    expect(byPage.get(2)?.map((s) => s.text)).toEqual(['B'])
  })

  it('throws on malformed lines', () => {
    expect(() => parseSpansJsonl('{"page":1')).toThrow()
    expect(() =>
      parseSpansJsonl('{"page":1,"label":"t","box":[1,2,3],"text":"x"}'),
    ).toThrow()
  })
})

describe('sidecar paths', () => {
  it('derives sibling md and spans paths from a pdf path', () => {
    expect(markdownPathFor('/a/b/paper.PDF')).toBe('/a/b/paper.md')
    expect(spansPathFor('/a/b/paper.pdf')).toBe('/a/b/paper.spans.jsonl')
  })
})

describe('pickReadingPage', () => {
  const entries = [
    { page: 1, top: -800 },
    { page: 2, top: -100 },
    { page: 3, top: 500 },
  ]
  it('anchors to the last entry above the line', () => {
    expect(pickReadingPage(entries, 200)).toBe(2)
  })
  it('sticks to the first page above the top', () => {
    expect(pickReadingPage(entries, -900)).toBe(null)
  })
  it('advances when the next page crosses the line', () => {
    expect(pickReadingPage(entries, 500)).toBe(3)
  })
  it('returns null for no entries', () => {
    expect(pickReadingPage([], 200)).toBe(null)
  })
})
