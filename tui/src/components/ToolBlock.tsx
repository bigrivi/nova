/** 工具调用块：状态头部 + 参数 + 结果（edit/write 的 diff 输出用 <diff> 渲染） */
import type { ToolCallPart as ToolCallPartData } from '../stores/chat-store.ts'

const DIFF_TOOLS = new Set(['edit', 'write', 'write_files', 'code_run'])

function looksLikeDiff(text: string): boolean {
  return /^(---|\+\+\+|@@)/m.test(text)
}

export function ToolBlock({ part }: { part: ToolCallPartData }) {
  const { toolName, status } = part
  const color =
    status === 'running' ? '#d29922' : status === 'error' ? '#e5534b' : '#3fb950'
  const marker = status === 'running' ? '●' : status === 'error' ? '✗' : '✓'

  return (
    <box
      flexDirection="column"
      paddingX={1}
      marginBottom={1}
      border
      borderStyle="rounded"
      borderColor={color}
    >
      <text fg={color}>
        {marker} {toolName}
        {status === 'running' ? '…' : ''}
      </text>
      {part.argsText && <text fg="#8b949e" content={part.argsText} />}
      {status === 'error' && part.error ? (
        <text fg="#e5534b" content={part.error} />
      ) : null}
      {status === 'done' && part.outputText ? (
        DIFF_TOOLS.has(toolName) && looksLikeDiff(part.outputText) ? (
          <diff diff={part.outputText} view="unified" showLineNumbers={false} />
        ) : (
          <text fg="#d0d7de" content={part.outputText} />
        )
      ) : null}
    </box>
  )
}
