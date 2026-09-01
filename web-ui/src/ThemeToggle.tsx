import { Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'

type Theme = 'light' | 'dark'

function preferredTheme(): Theme {
  const saved = window.localStorage.getItem('lghs-fleet-theme')
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => preferredTheme())

  useEffect(() => {
    applyTheme(theme)
    window.localStorage.setItem('lghs-fleet-theme', theme)
  }, [theme])

  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button className="icon-button" type="button" onClick={() => setTheme(next)} aria-label={`Use ${next} theme`} title={`Use ${next} theme`}>
      {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </button>
  )
}

export function initializeTheme() {
  applyTheme(preferredTheme())
}
