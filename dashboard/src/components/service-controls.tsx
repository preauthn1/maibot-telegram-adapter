import { useQuery, useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { backendApi } from '@/lib/http'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'

type Action = 'start' | 'stop' | 'restart'
type Status = { ActiveState: string; SubState: string; MainPID: string; Result: string }
const labels = { start: '启动', stop: '停止', restart: '重启' }
export function ServiceControls() {
  const [pending, setPending] = useState<Action | null>(null)
  const [feedback, setFeedback] = useState('')
  const status = useQuery({ queryKey: ['maibot-systemd'], queryFn: () => backendApi.get<Status>('/api/webui/system/service'), refetchInterval: 3000 })
  const mutation = useMutation({
    mutationFn: (action: Action) => backendApi.post<Status>(`/api/webui/system/service/${action}`, { headers: { 'X-MaiBot-Service-Control': '1' } }),
    onSuccess: async () => { setFeedback('命令已执行；以下为 systemd 状态，不代表 Telegram 已登录。'); setPending(null); await status.refetch() },
    onError: (error: Error) => { setFeedback(error.message); void status.refetch() },
  })
  return <Card data-testid="service-controls">
    <CardHeader><CardTitle>MaiBot 主服务控制</CardTitle></CardHeader>
    <CardContent className="space-y-3">
      <p>固定服务：maibot.service · 控制面板独立运行</p>
      <p role="status">{status.isError ? '状态读取失败：' + status.error.message : status.data ? `${status.data.ActiveState} / ${status.data.SubState} · PID ${status.data.MainPID} · ${status.data.Result}` : '正在读取状态…'}</p>
      <div className="flex gap-2">{(['start', 'stop', 'restart'] as Action[]).map(action => <Button key={action} disabled={!status.data || status.isError || mutation.isPending} onClick={() => { setPending(action); setFeedback('') }}>{labels[action]}主服务</Button>)}<Button variant="outline" onClick={() => void status.refetch()}>刷新状态</Button></div>
      {pending && <div role="alert" className="space-y-2"><p>确认{labels[pending]} maibot.service？启动或重启会恢复账号自动收发消息；停止不会关闭控制面板。</p><Button disabled={mutation.isPending} onClick={() => mutation.mutate(pending)}>{mutation.isPending ? '执行中…' : '确认执行'}</Button><Button variant="outline" disabled={mutation.isPending} onClick={() => setPending(null)}>取消</Button></div>}
      {feedback && <p role="alert">{feedback}</p>}
    </CardContent>
  </Card>
}
