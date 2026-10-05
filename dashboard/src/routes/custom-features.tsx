import { useQuery } from '@tanstack/react-query'
import { ExternalLink, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ApiError, backendApi } from '@/lib/http'

type FileStatus = {
  status: string
  message?: string
  bytes?: number
  modified_at?: string
}
type Snapshot = {
  observed_at: string
  runtime_note: string
  profiles: {
    status: string
    limited: boolean
    groups: Array<{
      group: string
      ownership: string
      parse_status: string
      file: FileStatus
      fields: Record<string, boolean | number | string>
    }>
    corpus: FileStatus
    source_note: string
    refresh_note: string
  }
  artifacts: Array<{
    name: string
    file: FileStatus
    structure?: { lines: number; sections: number }
    counters?: Record<string, number>
    preview?: string
    preview_note?: string
  }>
  guards: {
    status: string
    events: Array<{ group: string; event: string; label: string; ts: string }>
    limited: boolean
    tail_only: boolean
    invalid_lines: number
    unreadable_files: number
    coverage: string
  }
  lab: { url: string; evidence: string; auth_note: string; isolation_note: string }
}

const statuses: Record<string, string> = {
  ok: '已读取', missing: '未发现', unreadable: '不可读取 / 路径不安全',
  oversize: '超过读取上限', unsafe: '不安全文件', invalid: '格式损坏',
  changed: '文件读取期间变化', absent: '无风格字段', ambiguous: '重复字段 / 来源歧义',
  unavailable: '无法解析',
}
const fields: Record<string, string> = {
  style_enabled: '档案风格开关', manual_style_enabled: '人工风格开关',
  allow_emoji_only: '允许纯表情', max_emoji: '表情上限',
  preserve_trailing_period: '保留句末句号', style_max_chars: '风格长度参考（字）',
  style_owner_samples: '档案本人样本数', peer_style_samples: '档案同群基线样本数',
  peer_median_chars: '同群长度中位数', peer_question_rate: '同群问句占比（0–1）',
  style_source: '来源标记', total_messages: '累计发言', got_reply: '有人接话',
  ignored: '无人接话', suspected: '被怀疑记录',
}

function timestamp(value?: string) {
  if (!value) return '未知'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '无有效时间' : parsed.toLocaleString('zh-CN')
}

function FileSummary({ file }: { file: FileStatus }) {
  return <div className="space-y-1 text-sm">
    <p>{statuses[file.status] ?? '未知状态'}{file.message ? `：${file.message}` : ''}</p>
    <p className="text-muted-foreground">文件修改时间：{timestamp(file.modified_at)}</p>
    {file.bytes !== undefined && <p className="text-muted-foreground">文件大小：{file.bytes.toLocaleString('zh-CN')} 字节</p>}
  </div>
}

function Values({ values }: { values: Record<string, boolean | number | string> }) {
  return <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
    {Object.entries(values).map(([key, value]) => <div key={key} className="rounded-md border p-2">
      <dt className="text-muted-foreground">{fields[key] ?? '未知字段'}</dt>
      <dd className="break-words font-medium">{typeof value === 'boolean' ? (value ? '开启' : '关闭') : String(value)}</dd>
    </div>)}
  </dl>
}

export function CustomFeaturesPage() {
  const query = useQuery({
    queryKey: ['custom-features-readonly'],
    queryFn: () => backendApi.get<Snapshot>('/api/webui/custom-features'),
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const data = query.data
  const error = query.error instanceof ApiError || query.error instanceof Error
    ? query.error.message : '读取失败，请检查登录状态与 API 注册。'

  return <main className="mx-auto w-full max-w-6xl space-y-6 p-4 md:p-6">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">自建功能 · 只读观察</h1>
        <p className="text-sm text-muted-foreground">风格档案、语料来源、改进产物与已落盘群级守卫事件。没有配置修改、发送消息或服务控制。</p>
      </div>
      <Button variant="outline" disabled={query.isFetching} onClick={() => void query.refetch()}>
        <RefreshCw aria-hidden="true" className="mr-2 h-4 w-4" />{query.isFetching ? '读取中' : '重新读取快照'}
      </Button>
    </header>
    {query.isPending && <p role="status">正在读取有限磁盘快照…</p>}
    {query.isError && <p role="alert" className="rounded-lg border border-destructive p-4 text-destructive">{error} 旧快照如仍显示，不代表本次读取成功。</p>}
    {data && <>
      <section aria-label="观察边界" className="space-y-2 rounded-lg border bg-muted/30 p-4 text-sm">
        <p className="font-medium">非实时 · 运行态未知</p>
        <p>{data.runtime_note}</p>
        <p>快照读取时间：{timestamp(data.observed_at)}。群档案保留业务群号以便对应；尚未取得可验证群名，成员身份与聊天原文均不回传。</p>
      </section>
      <Card>
        <CardHeader><CardTitle>按群风格档案与语料归属</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">目录状态：{statuses[data.profiles.status] ?? '未知'}；仅展示最多 64 个群档案，不展示私聊档案。</p>
          <p className="text-sm">{data.profiles.source_note}</p>
          <div className="rounded-lg border p-3"><h3 className="mb-2 font-medium">操作员声明的本人语料文件</h3><FileSummary file={data.profiles.corpus} /></div>
          <p className="text-sm text-muted-foreground">{data.profiles.refresh_note}</p>
          {data.profiles.limited && <p role="status" className="text-sm">目录条目达到读取上限；当前结果不完整。</p>}
          {data.profiles.groups.length === 0 && <p className="text-sm">本次未读到可展示的群档案；不等于风格功能未启用。</p>}
          <div className="grid min-w-0 gap-4 md:grid-cols-2">
            {data.profiles.groups.map(group => <article key={group.group} className="min-w-0 space-y-3 rounded-lg border p-4">
              <h3 className="font-medium">{group.group}</h3>
              <p className="text-sm">{group.ownership}</p>
              <FileSummary file={group.file} />
              <p className="text-sm">字段解析：{statuses[group.parse_status] ?? '未知'}</p>
              <Values values={group.fields} />
            </article>)}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>自我改进 SOUL / SKILL 产物</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">只展示产物状态、结构与白名单累计计数。正文可能包含私聊、成员姓名、引述与避免话术，已完整隐藏。累计计数是原状态文件记录，不代表效果评估；没有修改历史或失败原因日志。</p>
          <div className="grid gap-4 md:grid-cols-3">
            {data.artifacts.map(item => <article key={item.name} className="min-w-0 space-y-3 rounded-lg border p-4">
              <h3 className="break-all font-medium">{item.name}</h3>
              <FileSummary file={item.file} />
              {item.structure && <p className="text-sm">{item.structure.lines} 行 / {item.structure.sections} 个标题段</p>}
              {item.preview !== undefined && <details className="text-sm"><summary className="cursor-pointer py-2">查看安全产物预览</summary><p className="my-2 text-muted-foreground">{item.preview_note}</p><pre className="whitespace-pre-wrap break-words rounded-md bg-muted/30 p-3">{item.preview || '未提取到白名单结构内容'}</pre></details>}
              {item.counters && <Values values={item.counters} />}
            </article>)}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>群级守卫 · 日志事件</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm">{data.guards.coverage}</p>
          <p className="text-sm text-muted-foreground">日志目录：{statuses[data.guards.status] ?? '未知'}；损坏/无法解析行：{data.guards.invalid_lines}；未读文件：{data.guards.unreadable_files}。</p>
          {(data.guards.limited || data.guards.tail_only) && <p role="status" className="text-sm">当前为受限日志窗口，不能推断所有历史拦截次数。</p>}
          {data.guards.events.length === 0 ? <p className="text-sm">当前窗口未读到可解析的已知群级拦截事件；不等于守卫未运行或没有发生拦截。</p> :
            <ol className="space-y-2">{data.guards.events.map((event, index) => <li key={`${event.group}-${event.event}-${event.ts}-${index}`} className="flex flex-wrap justify-between gap-2 rounded-lg border p-3 text-sm">
              <div><span className="font-medium">{event.label}</span><span className="ml-3 text-muted-foreground">{event.group}</span></div>
              <time dateTime={event.ts}>{timestamp(event.ts)}</time>
            </li>)}</ol>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>独立群聊实验室</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>{data.lab.evidence}</p><p>{data.lab.auth_note}</p><p>{data.lab.isolation_note}</p>
          <a href={data.lab.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" className="inline-flex min-h-11 items-center gap-2 rounded-md border px-4 font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            在新标签页打开实验室（需独立登录）<ExternalLink aria-hidden="true" className="h-4 w-4" />
          </a>
        </CardContent>
      </Card>
    </>}
  </main>
}
