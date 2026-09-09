// Throwaway visual verification for the library UI (fullstack-coder gauntlet):
// asserts zero console errors/pageerrors and probes interaction state via DOM.
import { chromium } from 'playwright'

const BASE = 'http://localhost:4173/'
const errors = []
const summary = {
  title: '',
  hasToolbar: false,
  hasTreeEmpty: false,
  hasMdPane: false,
  healthDot: false,
  pdfHint: false,
}

const browser = await chromium.launch()
const page = await browser.newPage()
page.on('response', (r) => {
  if (r.status() >= 400) errors_console.push(`http ${r.status()}: ${r.url()}`)
})
page.on('console', (msg) => {
  if (msg.type() === 'error') errors_console.push(msg.text())
})
const errors_console = []
page.on('pageerror', (err) => errors_console.push(`pageerror: ${String(err)}`))

await page.goto(BASE, { waitUntil: 'networkidle' })

// Tauri APIs are absent in a plain browser: getRoot invoke rejects -> the app
// should still render the shell with the no-folder empty state.
summary.title = await page.title()
summary.hasToolbar = await page
  .getByRole('button', { name: /open root/i })
  .first()
  .isVisible()
  .catch(() => false)
summary.hasTreeEmpty = await page
  .getByText('No folder open.')
  .first()
  .isVisible()
  .catch(() => false)
summary.hasMdPane = await page
  .getByText(/select a pdf|no sidecar|no folder/i)
  .count()
summary.pdfHint = await page
  .getByText('Select a PDF in the tree to preview it.')
  .isVisible()
  .catch(() => false)

await page.screenshot({ path: '/tmp/ui-shell.png', fullPage: false })

console.log(JSON.stringify({ summary, consoleErrors: errors_console }, null, 2))
await browser.close()
if (errors_console.length > 0) process.exit(2)
