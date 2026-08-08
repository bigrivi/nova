import type { TuiMessage } from '../stores/chat-store.ts'

export function UserMessage({ message }: { message: TuiMessage }) {
  const text = message.parts[0]?.type === 'text' ? message.parts[0].text : ''
  return (
    <box
      flexDirection="column"
      paddingX={2}
      paddingTop={1}
      paddingBottom={1}
      marginBottom={1}
      minHeight={3}
      justifyContent="center"
      backgroundColor="#1a2332"
    >
      <text content={text} />
    </box>
  )
}
