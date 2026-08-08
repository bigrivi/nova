/** 消息列表：ScrollBox 虚拟滚动 + 角色路由 */
import { useChatStore } from '../stores/chat-store.ts'
import { UserMessage } from './UserMessage.tsx'
import { AssistantMessage } from './AssistantMessage.tsx'

export function MessageList() {
  const messages = useChatStore((state) => state.messages)

  return (
    <scrollbox
      flexGrow={1}
      scrollY
      stickyScroll
      stickyStart="bottom"
      viewportCulling
    >
      {messages.map((msg) =>
        msg.role === 'user' ? (
          <UserMessage key={msg.id} message={msg} />
        ) : (
          <AssistantMessage key={msg.id} message={msg} />
        ),
      )}
    </scrollbox>
  )
}
