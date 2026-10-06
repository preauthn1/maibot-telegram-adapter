import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { backendApi } from '@/lib/http'
import type { MaiBotServiceStatus } from '@/lib/system-api'

type Action = 'start' | 'stop' | 'restart'
const actions: Action[] = ['start', 'stop', 'restart']
const labels = { start: '启动', stop: '停止', restart: '重启' }

export function ServiceControls() {
  const [pending, setPending] = useState<Action | null>(null)
  const [feedback, setFeedback] = useState('')
  const status = useQuery({
    queryKey: ['maibot-systemd'],
    queryFn: () => backendApi.get<MaiBotServiceStatus>('/api/webui/system/service'),
    refetchInterval: 3000,
  })
  // 必须由后端明确报告已授权的独立控制面；缺失或内嵌模式一律只读。
  const controlAvailable = !status.isError && status.data?.control_available === true &&
    status.data.control_mode === 'independent' && status.data.webui_lifecycle === 'independent'
  const mutation = useMutation({
    mutationFn: (action: Action) => {
      if (!controlAvailable) throw new Error('当前部署不允许主服务控制，请刷新状态。')
      return backendApi.post<MaiBotServiceStatus>(`/api/webui/system/service/${action}`, {
        headers: { 'X-MaiBot-Service-Control': '1' },
      })
    },
    onSuccess: async () => {
      setFeedback('命令已执行；以下为 systemd 状态，不代表核心就绪或 Telegram 已登录。')
      setPending(null)
      await status.refetch()
    },
    onError: (error: Error) => {
      setFeedback(error.message)
      setPending(null)
      void status.refetch()
    },
  })
  const unavailable = !controlAvailable || status.isFetching || mutation.isPending
  const running = typeof status.data?.running === 'boolean' ? status.data.running : null
  const transitioning = ['activating', 'deactivating', 'reloading'].includes(
    status.data?.ActiveState ?? '',
  )
  const lifecycleText = status.data?.webui_lifecycle === 'coupled'
    ? 'WebUI 与核心生命周期耦合；停止或重启主服务会使控制面板断开，因此主服务控制已禁用。'
    : status.data?.webui_lifecycle === 'independent'
      ? controlAvailable
        ? 'WebUI 独立运行；主服务控制已授权。'
        : 'WebUI 独立运行，但此部署未开放主服务控制。'
      : 'WebUI 生命周期尚未确认；主服务控制不可用。'

  return (
    <Card data-testid="service-controls">
      <CardHeader><CardTitle>MaiBot 主服务状态与控制</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">固定服务：maibot.service · {lifecycleText}</p>
        <p className="text-sm text-muted-foreground">这里只观察核心进程，不证明账号连接或消息收发。首页原有的核心重启入口不受此控制门控影响。</p>
        <p role="status" aria-live="polite" className="break-words text-sm tabular-nums">
          {status.isError
            ? `状态读取失败：${status.error.message}`
            : status.data
              ? `${status.data.ActiveState ?? '未知'} / ${status.data.SubState ?? '未知'} · 主服务 PID ${status.data.MainPID ?? '未知'} · WebUI PID ${status.data.webui_pid ?? '未知'}${status.data.Result ? ` · ${status.data.Result}` : ''}`
              : '正在读取状态…'}
        </p>
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <Button
              key={action}
              variant={action === 'start' ? 'default' : 'outline'}
              disabled={unavailable || transitioning || (action === 'start' ? running !== false : running !== true)}
              onClick={() => { setPending(action); setFeedback('') }}
            >
              {labels[action]}主服务
            </Button>
          ))}
          <Button
            variant="outline"
            disabled={status.isFetching || mutation.isPending}
            onClick={() => void status.refetch()}
          >刷新状态</Button>
        </div>
        {pending && (
          <div role="alert" className="space-y-3 rounded-md border p-3">
            <p className="text-sm leading-relaxed">
              确认{labels[pending]} maibot.service？此操作会改变核心进程状态，不保证账号自动恢复连接或收发消息。{lifecycleText}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button disabled={unavailable || transitioning} onClick={() => mutation.mutate(pending)}>
                {mutation.isPending ? '执行中…' : '确认执行'}
              </Button>
              <Button variant="outline" disabled={mutation.isPending} onClick={() => setPending(null)}>取消</Button>
            </div>
          </div>
        )}
        {feedback && <p role="alert" className="break-words text-sm leading-relaxed">{feedback}</p>}
      </CardContent>
    </Card>
  )
}
