import { createFileRoute } from '@tanstack/react-router'

import { LibraryPage } from '#/features/library/pages/library-page'

export const Route = createFileRoute('/')({
  component: LibraryPage,
})
