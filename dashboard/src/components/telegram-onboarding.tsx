import { useEffect, useRef, useState } from 'react'
import { ApiError, backendApi } from '@/lib/http'
import { Button } from './ui/button'
import { Input } from './ui/input'

const API = '/api/webui/telegram-onboarding'
const HEADER = { 'X-Telegram-Onboarding': '1' }
type Step = 'credentials' | 'code' | 'password' | 'done'
type StatusPayload = {
  configured: boolean
  proxy_configured: boolean
  device: { device_model: string; system_version: string; app_version: string }
  api_id?: number
  api_hash: string
  credentials_saved: boolean
}
type StepPayload = { step: Step; attempt_id?: string; expires_in?: number }

export function TelegramOnboarding() {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<Step>('credentials')
  const [mode, setMode] = useState<'phone' | 'import'>('phone')
  const [apiId, setApiId] = useState('')
  const [hash, setHash] = useState('')
  const [savedCreds, setSavedCreds] = useState(false)
  const [phone, setPhone] = useState('')
  const [session, setSession] = useState('')
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [remaining, setRemaining] = useState(0)
  const attempt = useRef('')
  const deadline = useRef(0)
  const clearSecrets = () => { setHash(''); setPhone(''); setSession(''); setValue('') }
  // 请求层（backendApi）负责 Cookie、HTML 回退诊断与 ApiError 文案，组件不再手写 response.json()
  const describe = (cause: unknown, fallback: string) =>
    cause instanceof ApiError || cause instanceof Error ? cause.message : fallback

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (deadline.current) {
        const seconds = Math.max(0, Math.ceil((deadline.current - Date.now()) / 1000))
        setRemaining(seconds)
        if (!seconds) {
          attempt.current = ''; deadline.current = 0
          setStep('credentials'); setValue(''); setError('登录已过期，请重新开始')
        }
      }
    }, 1000)
    return () => {
      window.clearInterval(timer)
      if (attempt.current) {
        void backendApi.delete(`${API}/${attempt.current}`, { headers: HEADER }).catch(() => undefined)
      }
    }
  }, [])

  async function show() {
    setOpen(true); setError('')
    try {
      const data = await backendApi.get<StatusPayload>(`${API}/status`, {
        cache: 'no-store', errorMessage: '无法读取登录状态',
      })
      setSavedCreds(Boolean(data.credentials_saved))
      setApiId(data.api_id ? String(data.api_id) : '')
      setInfo(`${data.configured ? '已有账号；新授权验证成功后才会替换。' : '尚未配置账号。'}固定代理：${data.proxy_configured ? '已配置' : '直连'}；设备：${data.device.device_model} / ${data.device.system_version} / ${data.device.app_version}`)
    } catch (cause) {
      setError(describe(cause, '无法读取状态'))
    }
  }

  async function submit() {
    setBusy(true); setError('')
    try {
      const path = step === 'credentials' ? '/start' : `/${attempt.current}/${step}`
      const body = step === 'credentials'
        ? {
            ...(!savedCreds ? { api_id: Number(apiId), api_hash: hash } : {}),
            phone: mode === 'phone' ? phone : '',
            session_string: mode === 'import' ? session : '',
            mode,
          }
        : { value }
      const data = await backendApi.post<StepPayload>(API + path, {
        body, headers: HEADER, errorMessage: '输入格式无效',
      })
      clearSecrets()
      if (data.attempt_id && data.expires_in) {
        attempt.current = data.attempt_id
        deadline.current = Date.now() + data.expires_in * 1000
        setRemaining(data.expires_in)
      }
      if (data.step === 'done') { attempt.current = ''; deadline.current = 0 }
      setStep(data.step)
    } catch (cause) {
      // 410 表示服务端已丢弃该登录尝试，必须回到首步而不是继续提交验证码
      if (cause instanceof ApiError && cause.status === 410) {
        attempt.current = ''; deadline.current = 0; setStep('credentials')
      }
      setError(describe(cause, '请求失败，请稍后重试'))
    } finally {
      setBusy(false); setValue('')
    }
  }

  async function cancel() {
    setBusy(true)
    try {
      if (attempt.current) {
        try {
          await backendApi.delete(`${API}/${attempt.current}`, { headers: HEADER })
        } catch (cause) {
          // 尝试已不存在时无需报错；其他失败要暴露，服务端仍会在十分钟内清理
          if (!(cause instanceof ApiError && cause.status === 410)) throw cause
        }
      }
      attempt.current = ''; deadline.current = 0
      clearSecrets(); setStep('credentials'); setOpen(false); setError('')
    } catch (cause) {
      setError(describe(cause, '取消失败，请重试；会话将在十分钟内自动清理'))
    } finally {
      setBusy(false)
    }
  }

  return <section className="space-y-3 rounded-xl border p-4" aria-label="Telegram 真人账号登录">
    <div className="flex items-center justify-between gap-3"><div><h2 className="font-semibold">Telegram 真人账号</h2><p className="text-muted-foreground text-sm">手机验证码、两步验证或 StringSession 导入；不会启动机器人。</p></div>
      {!open && <Button onClick={() => void show()}>添加 / 更换 Telegram 账号</Button>}</div>
    {open && <form className="max-w-xl space-y-3" autoComplete="off" onSubmit={e => { e.preventDefault(); void submit() }}>
      <p className="text-muted-foreground text-sm">{info}</p>
      <p className="text-sm">代理和设备参数继承服务器现有配置，登录期间不可修改。临时登录十分钟后自动断开。仅支持替换当前适配器的一个账号。</p>
      {step === 'credentials' && <>
        <label className="block text-sm">登录方式<select aria-label="登录方式" value={mode} onChange={e => setMode(e.target.value as 'phone' | 'import')} className="bg-background ml-3 rounded border p-2" disabled={busy}><option value="phone">手机验证码</option><option value="import">导入 StringSession</option></select></label>
        {savedCreds ? <p data-testid="saved-telegram-credentials" className="text-sm">API ID：{apiId}；API Hash：{'********'}（服务器已保存，自动复用，不下发明文）</p> : <>
          <p role="status">服务器 API 凭据缺失或无效，请先配置，或同时填写以下两项。</p>
          <label className="block text-sm">API ID<Input aria-label="API ID" type="number" min="1" required value={apiId} onChange={e => setApiId(e.target.value)} disabled={busy} /></label>
          <label className="block text-sm">API Hash<Input aria-label="API Hash" type="password" autoComplete="new-password" required minLength={32} maxLength={32} value={hash} onChange={e => setHash(e.target.value)} disabled={busy} /></label>
        </>}
        {mode === 'phone' ? <label className="block text-sm">手机号（含国际区号）<Input aria-label="手机号" type="tel" placeholder="+861****0000" pattern="\+[1-9][0-9]{6,14}" required value={phone} onChange={e => setPhone(e.target.value)} disabled={busy} /></label>
          : <label className="block text-sm">StringSession<Input aria-label="StringSession" type="password" autoComplete="new-password" required value={session} onChange={e => setSession(e.target.value)} disabled={busy} /></label>}
      </>}
      {(step === 'code' || step === 'password') && <>
        <p className="text-sm">剩余 {remaining} 秒。{step === 'code' ? '请查看 Telegram 客户端或短信中的验证码。' : '账号启用了两步验证，请输入 Telegram 密码。'}</p>
        <label className="block text-sm">{step === 'code' ? '验证码' : '两步验证密码'}<Input aria-label={step === 'code' ? '验证码' : '两步验证密码'} type="password" autoComplete="off" required value={value} onChange={e => setValue(e.target.value)} disabled={busy} /></label>
      </>}
      {step === 'done' && <p role="status">Telegram 授权已验证并安全保存。机器人运行状态未改变；启用前请检查适配器白名单和行为设置。</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <div className="flex gap-2">{step !== 'done' && <Button type="submit" disabled={busy}>{busy ? '处理中…' : step === 'credentials' ? mode === 'phone' ? '发送验证码' : '验证并导入' : '验证并继续'}</Button>}
        <Button type="button" variant="outline" onClick={() => void cancel()} disabled={busy}>{step === 'done' ? '完成' : '取消登录'}</Button></div>
    </form>}
  </section>
}
