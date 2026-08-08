/** 文本 part：OpenTUI markdown 流式渲染（含代码块 tree-sitter 语法高亮） */
import { useMemo } from 'react'
import { SyntaxStyle, getTreeSitterClient } from '@opentui/core'

const TOKEN_STYLES = {
  keyword: { fg: '#ff7b72' },
  string: { fg: '#a5d6ff' },
  comment: { fg: '#8b949e' },
  function: { fg: '#d2a8ff' },
  'type': { fg: '#ffa657' },
  'type.builtin': { fg: '#ffa657' },
  number: { fg: '#79c0ff' },
  boolean: { fg: '#79c0ff' },
  constant: { fg: '#79c0ff' },
  property: { fg: '#79c0ff' },
  operator: { fg: '#ff7b72' },
  punctuation: { fg: '#c9d1d9' },
  variable: { fg: '#e6edf3' },
  parameter: { fg: '#e6edf3' },
} as const

export function MarkdownPart({
  text,
  streaming,
}: {
  text: string
  streaming: boolean
}) {
  const syntaxStyle = useMemo(() => SyntaxStyle.fromStyles(TOKEN_STYLES), [])
  const treeSitterClient = useMemo(() => getTreeSitterClient(), [])
  return (
    <markdown
      content={text}
      streaming={streaming}
      syntaxStyle={syntaxStyle}
      treeSitterClient={treeSitterClient}
      conceal
    />
  )
}
