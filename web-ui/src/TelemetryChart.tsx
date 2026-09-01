import { useEffect, useRef } from 'react'
import { Download } from 'lucide-react'
import { LineChart } from 'echarts/charts'
import { AriaComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import type { EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, AriaComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

export interface TelemetryPoint {
  at: number
  cpuPct: number
  memPct: number
}

function css(name: string, fallback: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

function chartOption(points: TelemetryPoint[]): EChartsCoreOption {
  const accent = css('--accent', '#7aa2f7')
  const success = css('--success', '#6fbd82')
  const text2 = css('--text-2', '#aeb6c2')
  const text3 = css('--text-3', '#788390')
  const border = css('--border', '#272d35')
  const borderStrong = css('--border-strong', '#343c46')

  return {
    animation: false,
    aria: {
      enabled: true,
      decal: { show: false },
      description: 'CPU and memory utilization over the selected time range, in percent. A complete data table is available directly below the chart.',
    },
    grid: { left: 42, right: 18, top: 36, bottom: 42, containLabel: false },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) => `${Number(value).toFixed(1)}%`,
      backgroundColor: css('--surface', '#111419'),
      borderColor: borderStrong,
      textStyle: { color: css('--text', '#e8ecf2') },
    },
    legend: {
      top: 0,
      left: 0,
      textStyle: { color: text2 },
      itemWidth: 14,
      itemHeight: 4,
    },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: borderStrong } },
      axisTick: { show: false },
      axisLabel: { color: text3 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: text3, formatter: '{value}%' },
      splitLine: { lineStyle: { color: border } },
    },
    dataZoom: [
      { type: 'inside', filterMode: 'none' },
    ],
    series: [
      {
        name: 'CPU',
        type: 'line',
        showSymbol: false,
        sampling: 'lttb',
        lineStyle: { width: 2, color: accent },
        itemStyle: { color: accent },
        emphasis: { focus: 'series' },
        data: points.map((point) => [point.at, point.cpuPct]),
      },
      {
        name: 'Memory',
        type: 'line',
        showSymbol: false,
        sampling: 'lttb',
        lineStyle: { width: 2, color: success },
        itemStyle: { color: success },
        emphasis: { focus: 'series' },
        data: points.map((point) => [point.at, point.memPct]),
      },
    ],
  }
}

function downloadCsv(points: TelemetryPoint[]) {
  const rows = ['timestamp,cpu_pct,memory_pct', ...points.map((point) => `${new Date(point.at).toISOString()},${point.cpuPct.toFixed(2)},${point.memPct.toFixed(2)}`)]
  const blob = new Blob([`${rows.join('\n')}\n`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `lghs-telemetry-${new Date().toISOString().replaceAll(':', '-')}.csv`
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function TelemetryChart({ points }: { points: TelemetryPoint[] }) {
  const target = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!target.current) return
    const chart = echarts.init(target.current, undefined, { renderer: 'canvas' })
    const applyTheme = () => chart.setOption(chartOption(points), true)
    applyTheme()

    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(target.current)
    const theme = new MutationObserver(applyTheme)
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

    return () => {
      theme.disconnect()
      resize.disconnect()
      chart.dispose()
    }
  }, [points])

  return (
    <div className="telemetry-figure">
      <div className="telemetry-chart" ref={target} role="img" aria-label="CPU and memory utilization time series" />
      <div className="telemetry-data-actions">
        <details>
          <summary>View chart data</summary>
          <div className="telemetry-data-table-wrap">
            <table className="telemetry-data-table">
              <caption>CPU and memory utilization data</caption>
              <thead><tr><th>Time</th><th>CPU</th><th>Memory</th></tr></thead>
              <tbody>
                {points.map((point) => (
                  <tr key={point.at}>
                    <td>{new Date(point.at).toLocaleString()}</td>
                    <td>{point.cpuPct.toFixed(1)}%</td>
                    <td>{point.memPct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
        <button className="button ghost compact" type="button" onClick={() => downloadCsv(points)}><Download aria-hidden="true" /> Download CSV</button>
      </div>
    </div>
  )
}
