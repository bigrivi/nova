/** Python 后端进程生命周期管理：spawn `python -m nova serve`、健康检查、退出清理 */
import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync, mkdirSync, openSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'
import { DEFAULT_API_BASE } from './api/nova-api.ts'

const PROJECT_ROOT = '/Users/andy/Workspace/codes/ai/nova'
const VENV_PYTHON = `${PROJECT_ROOT}/.venv/bin/python3`

const HEALTH_TIMEOUT_MS = 15_000
const HEALTH_POLL_INTERVAL_MS = 300
const STOP_GRACE_MS = 2_000

let child: ChildProcess | null = null

export function backendPort(): number {
  return Number(process.env.NOVA_BACKEND_PORT ?? new URL(DEFAULT_API_BASE).port)
}

function pickPython(): string {
  // 优先项目虚拟环境，保证依赖完整
  return existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3'
}

async function waitForHealthy(baseUrl: string): Promise<void> {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${baseUrl}/health`)
      if (res.ok) {
        return
      }
    } catch {
      // backend not up yet
    }
    await sleep(HEALTH_POLL_INTERVAL_MS)
  }
  throw new Error(
    `Nova backend did not become healthy within ${HEALTH_TIMEOUT_MS}ms at ${baseUrl}`,
  )
}

/** 后端日志文件：避免 uvicorn 访问日志污染 TUI 终端渲染 */
function backendLogPath(): string {
  const home = process.env.NOVA_HOME || join(homedir(), '.nova')
  const dir = join(home, 'logs')
  try {
    mkdirSync(dir, { recursive: true })
  } catch {
    // 日志目录不可用时退化为当前目录
    return 'nova-tui-backend.log'
  }
  return join(dir, 'nova-tui-backend.log')
}

/** 启动 Python 后端并等待健康。已有实例在跑则直接复用（健康检查通过即可）。 */
export async function startBackend(): Promise<void> {
  const port = backendPort()
  const baseUrl = `http://127.0.0.1:${port}`

  // 若端口已被占用且健康，说明外部已有一个后端实例，直接复用
  try {
    const res = await fetch(`${baseUrl}/health`)
    if (res.ok) {
      console.log(`[tui] Reusing existing Nova backend at ${baseUrl}`)
      return
    }
  } catch {
    // continue to spawn
  }

  const python = pickPython()
  const logPath = backendLogPath()
  console.log(
    `[tui] Starting Nova backend (${python} -m nova serve) on port ${port} (logs: ${logPath})`,
  )
  const logFd = openSync(logPath, 'a')
  child = spawn(python, ['-m', 'nova', 'serve'], {
    cwd: PROJECT_ROOT,
    // stdout/stderr 重定向到日志文件，保持终端干净
    stdio: ['ignore', logFd, logFd],
    env: { ...process.env, NOVA_BACKEND_PORT: String(port) },
  })

  child.on('exit', (code) => {
    if (child && !child.killed) {
      console.log(`[tui] Backend exited with code ${code} (logs: ${logPath})`)
    }
    child = null
  })
  child.on('error', (err) => {
    console.error(`[tui] Failed to spawn backend: ${err.message}`)
  })

  await waitForHealthy(baseUrl)
  console.log(`[tui] Backend ready at ${baseUrl}`)
}

/** 停止后端子进程（SIGTERM → 超时后 SIGKILL）。 */
export async function stopBackend(): Promise<void> {
  const proc = child
  if (!proc) {
    return
  }
  child = null
  if (proc.exitCode !== null) {
    return // already exited
  }
  proc.kill('SIGTERM')
  const deadline = Date.now() + STOP_GRACE_MS
  while (proc.exitCode === null && Date.now() < deadline) {
    await sleep(50)
  }
  if (proc.exitCode === null) {
    proc.kill('SIGKILL')
  }
}
