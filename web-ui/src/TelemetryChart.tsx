import { useEffect, useMemo, useRef } from 'react'
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

export function TelemetryChart({ points }: { points: TelemetryPoint[] }) {
  const target = useRef<HTMLDivElement | null>(null)

  const option = useMemo<EChartsCoreOption>(() => ({
    animation: false,
    aria: {
      enabled: true,
      decal: { show: false },
      description: 'CPU and memory utilization over the selected time range, in percent.',
    },
    grid: { left: 42, right: 18, top: 36, bottom: 42, containLabel: false },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) => `${Number(value).toFixed(1)}%`,
    },
    legend: {
      top: 0,
      left: 0,
      textStyle: { color: '#aeb6c2' },
      itemWidth: 14,
      itemHeight: 4,
    },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: '#343a43' } },
      axisTick: { show: false },
      axisLabel: { color: '#788390' },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: '#788390', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#252a31' } },
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
        lineStyle: { width: 2, color: '#7aa2f7' },
        itemStyle: { color: '#7aa2f7' },
        data: points.map((point) => [point.at, point.cpuPct]),
      },
      {
        name: 'Memory',
        type: 'line',
        showSymbol: false,
        sampling: 'lttb',
        lineStyle: { width: 2, color: '#9ece6a' },
        itemStyle: { color: '#9ece6a' },
        data: points.map((point) => [point.at, point.memPct]),
      },
    ],
  }), [points])

  useEffect(() => {
    if (!target.current) return
    const chart = echarts.init(target.current, undefined, { renderer: 'canvas' })
    chart.setOption(option)
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(target.current)
    return () => {
      resize.disconnect()
      chart.dispose()
    }
  }, [option])

  return <div className="telemetry-chart" ref={target} role="img" aria-label="CPU and memory utilization time series" />
}
