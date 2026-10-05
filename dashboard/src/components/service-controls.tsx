import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { backendApi } from '@/lib/http'

type Action = 'start' | 'stop' | 'restart'
type Status = { ActiveState: string; SubState: string; MainPID: string; Result: string }
const actions: Action[] = ['start', 'stop', 'restart']
const labels = { start: '启动', stop: '停止', restart: '重启' }

export function ServiceControls() {
  const [pending, setPending] = useState<Action | null>(null)
  const [feedback, setFeedback] = useState('')
  const status = useQuery({
    queryKey: ['maibot-systemd'],
    queryFn: () => backendApi.get<Status>('/api/webui/system/service'),
    refetchInterval: 3000,
  })
  const mutation = useMutation({
    mutationFn: (action: Action) =>
      backendApi.post<Status>(`/api/webui/system/service/${action}`, {
        headers: { 'X-MaiBot-Service-Control': '1' },
      }),
    onSuccess: async () => {
      setFeedback('命令已执行；以下为 systemd 状态，不代表 Telegram 已登录。')
      setPending(null)
      await status.refetch()
    },
    onError: (error: Error) => {
      setFeedback(error.message)
      setPending(null)
      void status.refetch()
    },
  })
  const unavailable = !status.data || status.isError || mutation.isPending
  const running = status.data?.ActiveState === 'active'
  const transitioning = ['activating', 'deactivating', 'reloading'].includes(
    status.data?.ActiveState ?? '',
  )

  return (
    <Card data-testid="service-controls">
      <CardHeader><CardTitle>MaiBot 主服务控制</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">固定服务：maibot.service · 控制面板独立运行</p>
        <p role="status" aria-live="polite" className="break-words text-sm tabular-nums">
          {status.isError
            ? `状态读取失败：${status.error.message}`
            : status.data
              ? `${status.data.ActiveState} / ${status.data.SubState} · PID ${status.data.MainPID} · ${status.data.Result}`
              : '正在读取状态…'}
        </p>
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <Button
              key={action}
              variant={action === 'start' ? 'default' : 'outline'}
              disabled={unavailable || transitioning || (action === 'start' ? running : action === 'stop' && !running)}
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
              确认{labels[pending]} maibot.service？启动或重启会恢复账号自动收发消息；停止不会关闭控制面板。
            </p>
            <div className="flex flex-wrap gap-2">
              <Button disabled={mutation.isPending} onClick={() => mutation.mutate(pending)}>
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
