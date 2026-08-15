import { NovaAppShell } from './app/NovaAppShell'
import { useZoom } from './lib/use-zoom'

function App() {
  useZoom()
  return <NovaAppShell />
}

export default App
