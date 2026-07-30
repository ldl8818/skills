#!/usr/bin/env node
// ego-spaces.mjs — ego lite agent task space 的机制化收尾工具
// 背景：completeTaskSpace 靠 Agent 在最后一轮主动调，会话被打断/上下文压缩就会漏，
// 残留 space 即残留浏览器窗口。本脚本提供两层机制兜底（安装方式见 references/ego-space-hooks.md）：
//   hook-stop           Claude Code Stop hook：本会话用过 ego-browser 且仍有 agent space → 阻断收尾并提醒（每会话每 space 只提醒一次）
//   hook-session-start  Claude Code SessionStart hook：全局闲置超过 IDLE_HOURS 的 agent space 判定为孤儿，自动回收
// 手动子命令：
//   list                列出 agent 持有的 task space
//   close <id...>       完成并关闭指定 space（completeTaskSpace keep:false）
//   keep <id> [--note]  标记该 space 为「有意保留」，两层机制都跳过它；space 消失后标记自动清理
//   unkeep <id>         撤销保留标记
// 状态目录 ~/.agents/data/ego-spaces/：
//   last-touch          最近一次 ego-browser 命令的 epoch 秒（由 PostToolUse hook 的 shell 单行写入）
//   keep.json           保留标记 {id: {ts, note}}
//   acks/<session>.json 每会话已提醒过的 space id（防重复唠叨；7 天后自动清理）

import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const pExecFile = promisify(execFile)

const STATE_DIR = path.join(os.homedir(), '.agents', 'data', 'ego-spaces')
const ACK_DIR = path.join(STATE_DIR, 'acks')
const KEEP_FILE = path.join(STATE_DIR, 'keep.json')
const TOUCH_FILE = path.join(STATE_DIR, 'last-touch')
const IDLE_HOURS = Number(process.env.EGO_SPACES_IDLE_HOURS || 2)
const LOCAL_BIN = path.join(os.homedir(), '.local', 'bin', 'ego-browser')
const EGO_BIN = fs.existsSync(LOCAL_BIN) ? LOCAL_BIN : 'ego-browser'

function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')) } catch { return fallback }
}
function writeJson(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(data, null, 2))
}
function readStdin() {
  try { return fs.readFileSync(0, 'utf8') } catch { return '' }
}

// ego lite 没运行时绝不调 ego-browser CLI——那会把浏览器拉起来
async function egoRunning() {
  try { await pExecFile('pgrep', ['-f', 'ego lite.app/Contents/MacOS/']); return true } catch { return false }
}

// 脚本从 stdin 喂入（等价 heredoc）：ego-browser 在 stdin 非 TTY 时读 stdin 当脚本、忽略 -e。
// 实测脚本里的 console.log 从 CLI 的 stderr 出来，所以两路都收。
async function egoEval(script) {
  const promise = pExecFile(EGO_BIN, ['nodejs'], { timeout: 20000 })
  promise.child.stdin.end(script)
  const { stdout, stderr } = await promise
  return stdout + '\n' + stderr
}

// @@ 前缀把结果行和运行时杂音区分开
function parseMarked(out) {
  const line = out.split('\n').map((l) => l.trim()).filter((l) => l.startsWith('@@')).pop()
  if (!line) throw new Error('ego-browser 无结果输出：' + out.slice(0, 200))
  return JSON.parse(line.slice(2))
}

async function listAgentSpaces() {
  const out = await egoEval('const s = await listTaskSpaces(); console.log("@@" + JSON.stringify(s))')
  return parseMarked(out).filter((s) => s.ownership === 'agent')
}

async function closeSpaces(ids) {
  const script = `
const results = []
for (const id of ${JSON.stringify(ids)}) {
  try { const r = await completeTaskSpace(id, { keep: false }); results.push({ id, ...r }) }
  catch (e) { results.push({ id, error: String((e && e.message) || e) }) }
}
console.log('@@' + JSON.stringify(results))`
  return parseMarked(await egoEval(script))
}

function loadKeeps() { return readJson(KEEP_FILE, {}) }

// space 已不存在的保留标记自动清掉
function pruneKeeps(keeps, liveIds) {
  let changed = false
  for (const id of Object.keys(keeps)) {
    if (!liveIds.has(Number(id))) { delete keeps[id]; changed = true }
  }
  if (changed) writeJson(KEEP_FILE, keeps)
  return keeps
}

async function hookStop() {
  const input = JSON.parse(readStdin() || '{}')
  if (input.stop_hook_active) return
  const transcript = input.transcript_path
  if (!transcript || !fs.existsSync(transcript)) return
  // 只在本会话真正驱动过 ego-browser 时才检查（opencli、纯文档编辑不触发）
  try { await pExecFile('grep', ['-q', 'ego-browser nodejs', transcript]) } catch { return }
  if (!(await egoRunning())) return

  const spaces = await listAgentSpaces()
  const keeps = pruneKeeps(loadKeeps(), new Set(spaces.map((s) => s.id)))
  const sessionId = String(input.session_id || 'unknown').replace(/[^\w-]/g, '')
  const ackFile = path.join(ACK_DIR, sessionId + '.json')
  const acked = new Set(readJson(ackFile, []))
  const pending = spaces.filter((s) => !keeps[s.id] && !acked.has(s.id))
  if (!pending.length) return

  // 先记 ack 再提醒：同一 space 每会话最多唠叨一次，绝不造成阻断循环
  writeJson(ackFile, [...acked, ...pending.map((s) => s.id)])
  const self = process.argv[1]
  const lines = pending.map((s) => `- id=${s.id} name="${s.name}" tabs=${JSON.stringify(s.recentTabTitles || [])}`)
  const reason = [
    'ego-browser 收尾检查：仍有 agent 持有的 task space 未关闭（每个都是一个残留浏览器窗口）：',
    ...lines,
    '逐个处置后再结束回复（本提醒每会话每 space 只出现一次）：',
    `- 本会话开的、不再需要 → 运行 node "${self}" close <id>`,
    `- 符合 keep:true 判据（用户明确要留页面 / 需用户在该页面手动操作）→ 运行 node "${self}" keep <id> --note "<理由>"，并在回复里告知用户`,
    '- 属于其他并行会话正在用的 → 不要动它，直接结束即可',
  ].join('\n')
  console.log(JSON.stringify({ decision: 'block', reason }))
}

async function hookSessionStart() {
  // 顺手清理 7 天前的会话 ack 文件
  try {
    for (const f of fs.readdirSync(ACK_DIR)) {
      const p = path.join(ACK_DIR, f)
      if (Date.now() - fs.statSync(p).mtimeMs > 7 * 24 * 3600 * 1000) fs.unlinkSync(p)
    }
  } catch {}

  if (!(await egoRunning())) return
  if (!fs.existsSync(TOUCH_FILE)) {
    // 首次安装：只建基线，不回收——此刻无法区分孤儿和在用
    fs.mkdirSync(STATE_DIR, { recursive: true })
    fs.writeFileSync(TOUCH_FILE, String(Math.floor(Date.now() / 1000)))
    return
  }
  const last = Number(fs.readFileSync(TOUCH_FILE, 'utf8').trim())
  if (!Number.isFinite(last) || Date.now() / 1000 - last < IDLE_HOURS * 3600) return

  const spaces = await listAgentSpaces()
  const keeps = pruneKeeps(loadKeeps(), new Set(spaces.map((s) => s.id)))
  const targets = spaces.filter((s) => !keeps[s.id])
  if (!targets.length) return

  const results = await closeSpaces(targets.map((s) => s.id))
  const ok = new Set(results.filter((r) => r.done).map((r) => r.id))
  const failed = results.filter((r) => !r.done)
  const parts = []
  if (ok.size) {
    const names = targets.filter((t) => ok.has(t.id)).map((t) => `「${t.name}」`).join('、')
    parts.push(`已回收 ${ok.size} 个闲置超过 ${IDLE_HOURS} 小时的孤儿 task space：${names}`)
  }
  if (failed.length) parts.push(`回收失败：${JSON.stringify(failed)}`)
  if (parts.length) console.log('[ego-spaces] ' + parts.join('；'))
}

const [cmd, ...rest] = process.argv.slice(2)
const isHook = cmd === 'hook-stop' || cmd === 'hook-session-start'
try {
  switch (cmd) {
    case 'list': {
      if (!(await egoRunning())) { console.error('ego lite 未运行'); process.exit(1) }
      console.log(JSON.stringify(await listAgentSpaces(), null, 2))
      break
    }
    case 'close': {
      const ids = rest.map(Number).filter(Number.isFinite)
      if (!ids.length) { console.error('用法：ego-spaces.mjs close <id...>'); process.exit(1) }
      const results = await closeSpaces(ids)
      const keeps = loadKeeps()
      for (const id of ids) delete keeps[id]
      writeJson(KEEP_FILE, keeps)
      console.log(JSON.stringify(results, null, 2))
      break
    }
    case 'keep': {
      const id = Number(rest[0])
      if (!Number.isFinite(id)) { console.error('用法：ego-spaces.mjs keep <id> [--note "<理由>"]'); process.exit(1) }
      const noteIdx = rest.indexOf('--note')
      const note = noteIdx >= 0 ? rest[noteIdx + 1] || '' : ''
      const keeps = loadKeeps()
      keeps[id] = { ts: Math.floor(Date.now() / 1000), note }
      writeJson(KEEP_FILE, keeps)
      console.log(`已标记保留：space ${id}${note ? `（${note}）` : ''}；Stop 门禁与闲置回收都会跳过它`)
      break
    }
    case 'unkeep': {
      const keeps = loadKeeps()
      delete keeps[Number(rest[0])]
      writeJson(KEEP_FILE, keeps)
      console.log(`已撤销保留标记：space ${rest[0]}`)
      break
    }
    case 'hook-stop': await hookStop(); break
    case 'hook-session-start': await hookSessionStart(); break
    default:
      console.error('用法：ego-spaces.mjs <list|close|keep|unkeep|hook-stop|hook-session-start>')
      process.exit(1)
  }
} catch (e) {
  if (isHook) process.exit(0) // 门禁自身出错必须放行，绝不卡住用户会话
  console.error(String((e && e.stack) || e))
  process.exit(1)
}
