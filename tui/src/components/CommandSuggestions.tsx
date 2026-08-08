/** 命令建议弹窗：显示匹配的斜杠命令，高亮选中项
 * 始终渲染 box 并用 visible 控制——OpenTUI reconciler 不支持 null 子节点（会导致兄弟组件 fiber 错乱） */
import type { CommandSpec } from '../commands.ts'

export function CommandSuggestions({
  items,
  selectedIndex,
}: {
  items: CommandSpec[]
  selectedIndex: number
}) {
  return (
    <box
      visible={items.length > 0}
      flexDirection="column"
      flexShrink={0}
      paddingX={1}
      paddingY={1}
      border
      borderStyle="single"
      borderColor="#444c56"
    >
      {items.slice(0, 6).map((item, index) => (
        <text
          key={item.id}
          height={1}
          fg={index === selectedIndex ? '#4f9cf9' : '#8b949e'}
          content={`${index === selectedIndex ? '▸ ' : '  '}${item.usage}  ${item.description}`}
        />
      ))}
      {items.length > 6 ? <text height={1} fg="#6e7681" content="  …" /> : null}
    </box>
  )
}
