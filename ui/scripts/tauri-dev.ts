// Dev launcher: runs `tauri dev` on the first free port from 1420 upward,
// so two Tauri apps on one machine never steal each other's frontend.
// The chosen port reaches vite through OCR_UI_PORT and the Tauri CLI
// through a --config devUrl override (merged over tauri.conf.json).
//
// Usage: bun run tauri:dev
import net from 'node:net'
import { spawn } from 'node:child_process'

const BASE_PORT = 1420
const TRIES = 20

function isFree(port: number): Promise<boolean> {
  // Probe by CONNECTING, not by binding: a bind probe on 127.0.0.1 misses
  // servers on the wildcard address, and vite itself will then happily
  // share the port (which is exactly the crosstalk this launcher prevents).
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: '127.0.0.1', port }, () => {
      socket.destroy()
      resolve(false)
    })
    socket.once('error', () => resolve(true))
    socket.setTimeout(500, () => {
      socket.destroy()
      resolve(true)
    })
  })
}

async function pickPort(): Promise<number> {
  for (let port = BASE_PORT; port < BASE_PORT + TRIES; port += 1) {
    if (await isFree(port)) return port
  }
  throw new Error(
    `no free port in ${String(BASE_PORT)}-${String(BASE_PORT + TRIES - 1)}`,
  )
}

const port = await pickPort()
console.log(`[tauri:dev] using port ${String(port)}`)

const child = spawn(
  'bunx',
  [
    'tauri',
    'dev',
    '--config',
    JSON.stringify({ build: { devUrl: `http://localhost:${String(port)}` } }),
  ],
  {
    env: { ...process.env, OCR_UI_PORT: String(port) },
    stdio: 'inherit',
  },
)

child.on('exit', (code) => process.exit(code ?? 0))
child.on('error', (cause) => {
  console.error('[tauri:dev] failed to start:', cause)
  process.exit(1)
})
