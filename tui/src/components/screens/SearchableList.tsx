/** 通用可搜索列表：过滤输入 + ↑↓ 选择 + Enter 确认 + Escape 关闭（模态层） */
import { useMemo, useRef, useState } from 'react'
import { useKeyboard } from '@opentui/react'
import type { InputRenderable } from '@opentui/core'

export function SearchableList<T>({
  title,
  items,
  filter,
  renderLabel,
  onSelect,
  onClose,
  emptyText = '(empty)',
}: {
  title: string
  items: T[]
  filter: (item: T, query: string) => boolean
  renderLabel: (item: T) => string
  onSelect: (item: T) => void
  onClose: () => void
  emptyText?: string
}) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(0)
  const inputRef = useRef<InputRenderable>(null)

  const filtered = useMemo(
    () => items.filter((item) => filter(item, query)),
    [items, filter, query],
  )

  const live = useRef({ filtered, selected })
  live.current = { filtered, selected }

  useKeyboard((key) => {
    const { filtered: list, selected: sel } = live.current
    if (key.name === 'up') {
      setSelected((i) => Math.max(0, i - 1))
      return
    }
    if (key.name === 'down') {
      setSelected((i) => Math.min(list.length - 1, i + 1))
      return
    }
    if (key.name === 'enter') {
      const item = list[sel]
      if (item) {
        onSelect(item)
      }
      return
    }
    if (key.name === 'escape') {
      onClose()
    }
  })

  return (
    <box
      position="absolute"
      left="15%"
      right="15%"
      top="15%"
      paddingX={2}
      paddingY={2}
      border
      borderStyle="rounded"
      borderColor="#4f9cf9"
      backgroundColor="#0d1117"
    >
      <text fg="#4f9cf9">{title}</text>
      <input
        ref={inputRef}
        flexGrow={1}
        focused
        placeholder="Filter…"
        placeholderColor="#6e7681"
        onChange={(value) => {
          setQuery(value)
          setSelected(0)
        }}
        onSubmit={() => {
          const { filtered: list, selected: sel } = live.current
          const item = list[sel]
          if (item) {
            onSelect(item)
          }
        }}
      />
      <box flexDirection="column">
        {filtered.slice(0, 12).map((item, index) => (
          <text
            key={index}
            height={1}
            fg={index === selected ? '#4f9cf9' : '#8b949e'}
            content={`${index === selected ? '▸ ' : '  '}${renderLabel(item)}`}
          />
        ))}
        {filtered.length > 12 ? (
          <text height={1} fg="#6e7681" content={`  … ${filtered.length} items`} />
        ) : null}
        {filtered.length === 0 ? (
          <text height={1} fg="#6e7681" content={`  ${emptyText}`} />
        ) : null}
      </box>
      <text fg="#6e7681">↑↓ select • enter confirm • esc close</text>
    </box>
  )
}
