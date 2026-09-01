import { useEffect, useRef } from 'react'

interface Point {
  x: number
  y: number
  r: number
  phase: number
  speed: number
  lane: number
}

const POINTS = 58
const FPS = 30

function cssColor(name: string, fallback: string) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

export function SignalField({ compact = false }: { compact?: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext('2d', { alpha: true })
    if (!context) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    let frame = 0
    let last = 0
    let width = 0
    let height = 0
    let dpr = 1
    let visible = !document.hidden
    let points: Point[] = []

    const seedPoints = () => {
      points = Array.from({ length: POINTS }, (_, index) => {
        const lane = index % 9
        const row = Math.floor(index / 9)
        return {
          x: (lane + 0.45 + ((row * 0.31) % 0.5)) / 9,
          y: (row + 0.55 + ((lane * 0.17) % 0.35)) / 7,
          r: index % 7 === 0 ? 1.7 : 1,
          phase: (index * 0.61803398875) % 1,
          speed: 0.035 + (index % 5) * 0.006,
          lane,
        }
      })
    }

    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      width = Math.max(1, rect.width)
      height = Math.max(1, rect.height)
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      seedPoints()
      draw(performance.now(), true)
    }

    const draw = (now: number, staticFrame = false) => {
      context.clearRect(0, 0, width, height)

      const accent = cssColor('--accent', '#7aa2f7')
      const quiet = cssColor('--signal-quiet', 'rgba(122,162,247,.15)')
      const line = cssColor('--signal-line', 'rgba(122,162,247,.10)')
      const warm = cssColor('--signal-warm', 'rgba(216,173,97,.55)')

      context.save()
      context.globalAlpha = 0.9

      const centerX = width * 0.66
      const centerY = height * 0.46
      const radius = Math.min(width, height) * (compact ? 0.31 : 0.38)

      context.strokeStyle = line
      context.lineWidth = 1
      for (let ring = 1; ring <= 4; ring += 1) {
        context.beginPath()
        context.arc(centerX, centerY, (radius * ring) / 4, 0, Math.PI * 2)
        context.stroke()
      }

      for (let index = 0; index < points.length; index += 1) {
        const point = points[index]
        const px = point.x * width
        const py = point.y * height
        const distance = Math.hypot(px - centerX, py - centerY)
        if (distance < radius * 1.17 || index % 4 === 0) {
          context.fillStyle = index % 11 === 0 ? warm : quiet
          context.fillRect(Math.round(px), Math.round(py), point.r * 2, point.r * 2)
        }
      }

      context.strokeStyle = line
      for (let index = 0; index < points.length - 1; index += 1) {
        const a = points[index]
        const b = points[(index + 9) % points.length]
        if (Math.abs(a.lane - b.lane) > 2) continue
        context.beginPath()
        context.moveTo(a.x * width, a.y * height)
        context.lineTo(b.x * width, b.y * height)
        context.stroke()
      }

      if (!staticFrame && !reduced.matches) {
        const seconds = now / 1000
        for (let index = 0; index < 7; index += 1) {
          const phase = (seconds * (0.045 + index * 0.004) + index * 0.137) % 1
          const angle = Math.PI * (0.87 + index * 0.085)
          const travel = radius * (0.18 + phase * 1.22)
          const px = centerX + Math.cos(angle) * travel
          const py = centerY + Math.sin(angle) * travel * 0.67
          const fade = 1 - Math.abs(phase - 0.55) * 1.45
          context.globalAlpha = Math.max(0.12, Math.min(0.82, fade))
          context.fillStyle = index === 2 ? warm : accent
          context.fillRect(Math.round(px), Math.round(py), index === 2 ? 4 : 3, index === 2 ? 4 : 3)
        }
      }

      context.restore()
    }

    const tick = (now: number) => {
      frame = 0
      if (!visible || reduced.matches) return
      if (now - last >= 1000 / FPS) {
        last = now
        draw(now)
      }
      frame = requestAnimationFrame(tick)
    }

    const start = () => {
      cancelAnimationFrame(frame)
      draw(performance.now(), true)
      if (!reduced.matches && visible) frame = requestAnimationFrame(tick)
    }

    const onVisibility = () => {
      visible = !document.hidden
      start()
    }

    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    reduced.addEventListener('change', start)
    document.addEventListener('visibilitychange', onVisibility)
    resize()
    start()

    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      reduced.removeEventListener('change', start)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [compact])

  return <canvas ref={canvasRef} className={`signal-field${compact ? ' signal-field-compact' : ''}`} aria-hidden="true" />
}
