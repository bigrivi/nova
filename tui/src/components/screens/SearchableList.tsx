/** 通用可搜索列表：过滤输入 + ↑↓ 选择 + PageUp/PageDown 翻页 + Enter 确认 + Escape 关闭 */
import type { InputRenderable } from '@opentui/core'
import { useKeyboard } from '@opentui/react'
import { useMemo, useRef, useState } from 'react'

const PAGE_SIZE = 12

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
  const [scrollOffset, setScrollOffset] = useState(0)
  const inputRef = useRef<InputRenderable>(null)

  const filtered = useMemo(
    () => items.filter((item) => filter(item, query)),
    [items, filter, query],
  )

  const live = useRef({ filtered, selected, scrollOffset })
  live.current = { filtered, selected, scrollOffset }

  useKeyboard((key) => {
    const { filtered: list, selected: sel, scrollOffset: off } = live.current
    if (key.name === 'up') {
      if (sel > 0) {
        setSelected(sel - 1)
      } else if (off > 0) {
        const nextOffset = off - 1
        setScrollOffset(nextOffset)
        setSelected(0)
      }
      return
    }
    if (key.name === 'down') {
      if (sel < list.length - 1 && sel < off + PAGE_SIZE - 1) {
        setSelected(sel + 1)
      } else if (sel < list.length - 1) {
        const nextOffset = off + 1
        setScrollOffset(nextOffset)
        setSelected(off + PAGE_SIZE)
      }
      return
    }
    if (key.name === 'pageup') {
      const nextOffset = Math.max(0, off - PAGE_SIZE)
      setScrollOffset(nextOffset)
      setSelected(nextOffset)
      return
    }
    if (key.name === 'pagedown') {
      const maxOffset = Math.max(0, list.length - PAGE_SIZE)
      const nextOffset = Math.min(maxOffset, off + PAGE_SIZE)
      setScrollOffset(nextOffset)
      setSelected(nextOffset)
      return
    }
    if (key.name === 'home') {
      setScrollOffset(0)
      setSelected(0)
      return
    }
    if (key.name === 'end') {
      const maxOffset = Math.max(0, list.length - PAGE_SIZE)
      setScrollOffset(maxOffset)
      setSelected(Math.min(list.length - 1, maxOffset + PAGE_SIZE - 1))
      return
    }
    if (key.name === 'return' || key.name === 'enter') {
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

  const visible = filtered.slice(scrollOffset, scrollOffset + PAGE_SIZE)
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.floor(scrollOffset / PAGE_SIZE) + 1

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
        value={query}
        placeholder="Filter…"
        placeholderColor="#6e7681"
        onChange={(value) => {
            setQuery(value)
            setSelected(0)
            setScrollOffset(0)
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
        {visible.map((item, index) => {
          const realIndex = scrollOffset + index
          return (
            <text
              key={realIndex}
              height={1}
              fg={realIndex === selected ? '#4f9cf9' : '#8b949e'}
              content={`${realIndex === selected ? '▸ ' : '  '}${renderLabel(item)}`}
            />
          )
        })}
        {filtered.length === 0 ? (
          <text height={1} fg="#6e7681" content={`  ${emptyText}`} />
        ) : null}
      </box>
      <text fg="#6e7681">
        {filtered.length > PAGE_SIZE
          ? `↑↓ select • PgUp/PgDn page ${currentPage}/${totalPages} • enter confirm • esc close`
          : '↑↓ select • enter confirm • esc close'}
      </text>
    </box>
  )
}
