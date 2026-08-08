/** Create Agent 屏幕：逐步表单（key → name → description）→ 创建 */
import { useRef, useState } from 'react'
import { useKeyboard } from '@opentui/react'
import type { InputRenderable } from '@opentui/core'
import { createAgent } from '../../api/nova-api.ts'
import { useScreenStore } from '../../stores/screen-store.ts'

const FIELDS = [
  { key: 'key', label: 'Agent key (3-32 chars: [a-z0-9-])', required: true },
  { key: 'name', label: 'Display name', required: true },
  { key: 'description', label: 'Description (optional)', required: false },
] as const

type FieldKey = (typeof FIELDS)[number]['key']
type Values = Record<FieldKey, string>

export function CreateAgentScreen() {
  const [step, setStep] = useState(0)
  const [values, setValues] = useState<Values>({ key: '', name: '', description: '' })
  const [error, setError] = useState('')
  const inputRef = useRef<InputRenderable>(null)

  const field = FIELDS[step]!

  useKeyboard((key) => {
    if (key.name === 'escape') {
      useScreenStore.getState().close()
    }
  })

  async function submit(valuesToUse: Values): Promise<void> {
    if (!valuesToUse.key || !valuesToUse.name) {
      return
    }
    useScreenStore.getState().close()
    try {
      await createAgent({
        key: valuesToUse.key,
        name: valuesToUse.name,
        description: valuesToUse.description,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <box
      position="absolute"
      left="20%"
      right="20%"
      top="20%"
      paddingX={2}
      paddingY={2}
      border
      borderStyle="rounded"
      borderColor="#4f9cf9"
      backgroundColor="#0d1117"
    >
      <text fg="#4f9cf9">Create Agent — {field.label}</text>
      <input
        ref={inputRef}
        flexGrow={1}
        focused
        placeholder={field.key === 'key' ? 'my-agent' : field.key === 'name' ? 'My Agent' : '(optional)'}
        placeholderColor="#6e7681"
        onSubmit={() => {
          const value = inputRef.current?.value ?? ''
          const next: Values = { ...values, [field.key]: value }
          setValues(next)
          if (field.required && !value.trim()) {
            return
          }
          if (step < FIELDS.length - 1) {
            inputRef.current?.clear()
            setStep(step + 1)
          } else {
            void submit(next)
          }
        }}
      />
      {error ? <text fg="#e5534b" content={error} /> : null}
      <text fg="#6e7681">
        {step + 1}/{FIELDS.length}  •  enter next  •  esc cancel
      </text>
    </box>
  )
}
