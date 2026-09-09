import { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  FileCheck2,
  Loader2,
} from 'lucide-react'

import { cn } from '#/lib/cn'
import type { TreeNode } from '../library.schema'

type TreeItemProps = {
  node: TreeNode
  depth: number
  selectedPath: string | null
  onSelect: (node: TreeNode) => void
  busyPdfPath: string | null
}

/** Icon for a leaf node. `busy` = an OCR job is running for its PDF. */
function LeafIcon({
  node,
  busy,
}: {
  node: TreeNode
  busy: boolean
}): React.JSX.Element {
  if (busy) {
    return (
      <Loader2
        className="size-3.5 shrink-0 animate-spin text-primary"
        aria-hidden
      />
    )
  }
  if (node.kind === 'pdf') {
    return node.hasMd ? (
      <FileCheck2 className="size-3.5 shrink-0 text-primary" aria-hidden />
    ) : (
      <FileText
        className="size-3.5 shrink-0 text-muted-foreground"
        aria-hidden
      />
    )
  }
  return (
    <FileText
      className="size-3.5 shrink-0 text-muted-foreground/60"
      aria-hidden
    />
  )
}

function TreeItem({
  node,
  depth,
  selectedPath,
  onSelect,
  busyPdfPath,
}: TreeItemProps): React.JSX.Element {
  const [open, setOpen] = useState(depth < 1)
  const isDir = node.kind === 'dir'
  const selected = node.path === selectedPath
  const busy = busyPdfPath !== null && node.path === busyPdfPath

  return (
    <div>
      <button
        type="button"
        onClick={() => (isDir ? setOpen((v) => !v) : onSelect(node))}
        className={cn(
          'flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-sm',
          'hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          selected && 'bg-muted font-medium',
        )}
        style={{ paddingLeft: `${String(depth * 14 + 8)}px` }}
        aria-expanded={isDir ? open : undefined}
      >
        {isDir ? (
          open ? (
            <ChevronDown
              className="size-3.5 shrink-0 text-muted-foreground"
              aria-hidden
            />
          ) : (
            <ChevronRight
              className="size-3.5 shrink-0 text-muted-foreground"
              aria-hidden
            />
          )
        ) : null}
        {isDir ? (
          open ? (
            <FolderOpen
              className="size-3.5 shrink-0 text-muted-foreground"
              aria-hidden
            />
          ) : (
            <Folder
              className="size-3.5 shrink-0 text-muted-foreground"
              aria-hidden
            />
          )
        ) : (
          <LeafIcon node={node} busy={busy} />
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isDir && open
        ? (node.children ?? []).map((child) => (
            <TreeItem
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              busyPdfPath={busyPdfPath}
            />
          ))
        : null}
    </div>
  )
}

type LibraryTreeProps = {
  tree: TreeNode | null
  selectedPath: string | null
  onSelect: (node: TreeNode) => void
  busyPdfPath: string | null
}

/** Left pane: the library file tree (dirs + pdf/md/jsonl files). */
export function LibraryTree({
  tree,
  selectedPath,
  onSelect,
  busyPdfPath,
}: LibraryTreeProps): React.JSX.Element {
  if (tree === null) {
    return (
      <p className="px-3 py-2 text-sm text-muted-foreground">
        No folder open. Choose a root folder to begin.
      </p>
    )
  }
  return (
    <nav aria-label="Library folders" className="py-1">
      {(tree.children ?? []).map((child) => (
        <TreeItem
          key={child.path}
          node={child}
          depth={0}
          selectedPath={selectedPath}
          onSelect={onSelect}
          busyPdfPath={busyPdfPath}
        />
      ))}
    </nav>
  )
}
