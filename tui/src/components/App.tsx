/** 根组件：布局编排、modal 层、全局快捷键与命令分发 */
import { useKeyboard } from '@opentui/react'
import { useApprovalStore } from '../stores/approval-store.ts'
import { useAskUserStore } from '../stores/ask-user-store.ts'
import { useChatStore } from '../stores/chat-store.ts'
import { useScreenStore } from '../stores/screen-store.ts'
import { ApprovalDialog } from './ApprovalDialog.tsx'
import { AskUserForm } from './AskUserForm.tsx'
import { Composer, type ComposerCommandHandler } from './Composer.tsx'
import { MessageList } from './MessageList.tsx'
import { AgentsScreen } from './screens/AgentsScreen.tsx'
import { CreateAgentScreen } from './screens/CreateAgentScreen.tsx'
import { ModelsScreen } from './screens/ModelsScreen.tsx'
import { SessionsScreen } from './screens/SessionsScreen.tsx'
import { StatusBar } from './StatusBar.tsx'

export type ExitHandler = () => void

export function App({ onExit }: { onExit: ExitHandler }) {
  const askQuestions = useAskUserStore((state) => state.active)
  const approval = useApprovalStore((state) => state.pending)
  const screen = useScreenStore((state) => state.current)

  useKeyboard((key) => {
    if (useAskUserStore.getState().active || useApprovalStore.getState().pending) {
      // modal 键盘由 AskUserForm / ApprovalDialog 处理
      return
    }
    if (useScreenStore.getState().current) {
      // 屏幕键盘由各 screen 的 useKeyboard 处理
      return
    }
    if (key.ctrl && key.name === 'c') {
      onExit()
    }
  })

  const handleCommand: ComposerCommandHandler = (id, _args) => {
    const screens = useScreenStore.getState()
    switch (id) {
      case 'new':
        useChatStore.getState().reset()
        return
      case 'clear':
        useChatStore.setState({ messages: [] })
        return
      case 'quit':
      case 'exit':
        onExit()
        return
      case 'sessions':
        screens.open({ kind: 'sessions' })
        return
      case 'models':
        screens.open({ kind: 'models' })
        return
      case 'list-agents':
        screens.open({ kind: 'agents' })
        return
      case 'create-agent':
        screens.open({ kind: 'create-agent' })
        return
      case 'delete-agent':
        screens.open({ kind: 'delete-agent' })
        return
      default:
        // /theme /install-skill /install-global-skill → 暂未实现
        return
    }
  }

  return (
    <box flexDirection="column" flexGrow={1} padding={0}>
      <text fg="#8b949e">Nova TUI — OpenTUI/React</text>
      <MessageList />
      <Composer onCommand={handleCommand} />
      <StatusBar />
      {askQuestions ? <AskUserForm questions={askQuestions} /> : null}
      {approval ? (
        <ApprovalDialog
          sessionId={approval.sessionId}
          requestId={approval.requestId}
          command={approval.command}
          description={approval.description}
        />
      ) : null}
      {screen?.kind === 'sessions' ? <SessionsScreen /> : null}
      {screen?.kind === 'models' ? <ModelsScreen /> : null}
      {screen?.kind === 'agents' || screen?.kind === 'delete-agent' ? (
        <AgentsScreen deletable={screen.kind === 'delete-agent'} />
      ) : null}
      {screen?.kind === 'create-agent' ? <CreateAgentScreen /> : null}
    </box>
  )
}
