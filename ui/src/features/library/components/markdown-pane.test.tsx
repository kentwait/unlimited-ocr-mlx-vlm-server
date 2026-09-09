// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  MarkdownPane,
  findSnippetBlock,
  normalizeSnippetText,
  splitByAnchors,
} from './markdown-pane'
import { fireEvent } from '@testing-library/react'

const DOC = [
  '# Title',
  '<!-- ocr:page:1 -->',
  'first page text',
  '<!-- ocr:page:2 -->',
  'second page text',
].join('\n')

describe('splitByAnchors', () => {
  it('splits on ocr:page anchors, trimming whitespace', () => {
    const chunks = splitByAnchors(DOC)
    expect(chunks).toEqual([
      { page: 1, content: 'first page text' },
      { page: 2, content: 'second page text' },
    ])
  })

  it('returns null when no anchors exist', () => {
    expect(splitByAnchors('# just a doc')).toBeNull()
  })

  it('drops empty chunks (anchor with no following content)', () => {
    const chunks = splitByAnchors('<!-- ocr:page:1 -->')
    expect(chunks).toEqual([])
  })

  it('keeps leading text before the first anchor out of chunks', () => {
    const chunks = splitByAnchors(DOC)
    expect(chunks?.map((c) => c.content)).not.toContain('# Title')
  })
})

describe('MarkdownPane', () => {
  it('renders anchored chunks and shows the page count', () => {
    render(
      <MarkdownPane
        markdown={DOC}
        currentPage={1}
        syncEnabled={false}
        scrollToken={0}
        emptyHint="empty"
      />,
    )
    expect(screen.getByText('first page text')).toBeInTheDocument()
    expect(screen.getByText('second page text')).toBeInTheDocument()
    expect(screen.getByText('2 pages')).toBeInTheDocument()
  })

  it('shows the empty hint when markdown is null', () => {
    render(
      <MarkdownPane
        markdown={null}
        currentPage={1}
        syncEnabled={false}
        scrollToken={0}
        emptyHint="no sidecar yet"
      />,
    )
    expect(screen.getByText('no sidecar yet')).toBeInTheDocument()
  })

  it('flags missing anchors in the header', () => {
    render(
      <MarkdownPane
        markdown="# plain doc"
        currentPage={1}
        syncEnabled={false}
        scrollToken={0}
        emptyHint="empty"
      />,
    )
    expect(
      screen.getByText('no page anchors — page sync off'),
    ).toBeInTheDocument()
  })

  it('notifies the selected page when a chunk is clicked', () => {
    const seen: number[] = []
    render(
      <MarkdownPane
        markdown={DOC}
        currentPage={1}
        syncEnabled={true}
        scrollToken={0}
        onChunkClick={(page) => seen.push(page)}
        emptyHint="empty"
      />,
    )
    fireEvent.click(screen.getByLabelText('Show PDF page 2'))
    expect(seen).toEqual([2])
  })

  it('does not make chunks clickable when sync is off', () => {
    const seen: number[] = []
    render(
      <MarkdownPane
        markdown={DOC}
        currentPage={1}
        syncEnabled={false}
        scrollToken={0}
        onChunkClick={(page) => seen.push(page)}
        emptyHint="empty"
      />,
    )
    expect(screen.queryByLabelText(/Show PDF page/)).toBeNull()
    expect(seen).toEqual([])
  })
})

describe('findSnippetBlock', () => {
  it('matches a long prefix case- and whitespace-insensitively', () => {
    const blocks = [
      'Introduction',
      'A global view of human centromere organization in 2026 changed everything.',
    ]
    expect(
      findSnippetBlock(
        blocks,
        'a  global VIEW of human centromere organization in 2026 changed everything and more',
      ),
    ).toBe(1)
  })

  it('falls back to shorter probes when the tail was rewritten', () => {
    const blocks = [
      'Methods',
      'We sequenced 2,110 centromeres from diverse samples.',
    ]
    expect(
      findSnippetBlock(
        blocks,
        'We sequenced 2,110 centromeres from entirely different cohorts today.',
      ),
    ).toBe(1)
  })

  it('returns -1 for short snippets and total misses', () => {
    expect(findSnippetBlock(['abc'], 'too short')).toBe(-1)
    expect(
      findSnippetBlock(
        ['The quick brown fox jumps over the lazy dog near the riverbank.'],
        'Zebra crossings in central Kyoto during rush hour traffic jams.',
      ),
    ).toBe(-1)
  })

  it('normalizes whitespace runs', () => {
    expect(normalizeSnippetText('  A\n B\tC ')).toBe('a b c')
  })
})
