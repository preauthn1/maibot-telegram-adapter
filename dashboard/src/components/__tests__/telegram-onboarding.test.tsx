import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TelegramOnboarding } from '../telegram-onboarding'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('@/lib/http', () => ({ backendApi: api, ApiError: class ApiError extends Error {} }))
afterEach(cleanup)
beforeEach(() => {
  vi.resetAllMocks()
  api.get.mockResolvedValue({ configured: true, proxy_configured: true, device: { device_model: 'test', system_version: 'test', app_version: 'test' }, api_id: 123, credentials_saved: true })
})
describe('Telegram 授权提交边界', () => {
  it('连续提交只创建一次授权尝试，取消不启动机器人', async () => {
    let finish!: (value: unknown) => void
    api.post.mockReturnValue(new Promise(resolve => { finish = resolve }))
    render(<TelegramOnboarding />)
    fireEvent.click(screen.getByRole('button', { name: '添加 / 更换 Telegram 账号' }))
    await screen.findByTestId('saved-telegram-credentials')
    fireEvent.change(screen.getByLabelText('手机号'), { target: { value: '+861234567890' } })
    const form = screen.getByRole('button', { name: '发送验证码' }).closest('form')!
    fireEvent.submit(form)
    fireEvent.submit(form)
    expect(api.post).toHaveBeenCalledTimes(1)
    finish({ step: 'code', attempt_id: 'fixture', expires_in: 600 })
    await screen.findByLabelText('验证码')
    api.delete.mockResolvedValue({})
    fireEvent.click(screen.getByRole('button', { name: '取消登录' }))
    await waitFor(() => expect(screen.queryByLabelText('验证码')).not.toBeInTheDocument())
    expect(api.delete).toHaveBeenCalledWith('/api/webui/telegram-onboarding/fixture', { headers: { 'X-Telegram-Onboarding': '1' } })
    expect(api.post).toHaveBeenCalledTimes(1)
  })
})
