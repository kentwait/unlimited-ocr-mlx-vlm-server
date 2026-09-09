// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MarkdownPane, splitByAnchors } from './markdown-pane'

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
        emptyHint="empty"
      />,
    )
    expect(
      screen.getByText('no page anchors — page sync off'),
    ).toBeInTheDocument()
  })
})
