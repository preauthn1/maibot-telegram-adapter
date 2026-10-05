import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ServiceControls } from '../service-controls'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/lib/http', () => ({ backendApi: api }))

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><ServiceControls /></QueryClientProvider>)
}

afterEach(cleanup)
beforeEach(() => {
  vi.resetAllMocks()
  api.get.mockResolvedValue({ ActiveState: 'inactive', SubState: 'dead', MainPID: '0', Result: 'success' })
})

describe('主服务控制', () => {
  it('使用真实服务状态禁用无意义操作，必须确认才发送命令', async () => {
    mount()
    await waitFor(() => expect(screen.getByRole('button', { name: '启动主服务' })).toBeEnabled(), { timeout: 10000 })
    expect(screen.getByRole('button', { name: '停止主服务' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '启动主服务' }))
    expect(api.post).not.toHaveBeenCalled()
    expect(screen.getByText(/恢复账号自动收发消息/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('button', { name: '确认执行' })).not.toBeInTheDocument()
  })

  it('失败后关闭旧确认，显示错误并回读状态，不自动重试变更', async () => {
    api.post.mockRejectedValue(new Error('操作失败，请刷新状态后重试'))
    mount()
    await waitFor(() => expect(screen.getByRole('button', { name: '启动主服务' })).toBeEnabled(), { timeout: 10000 })
    fireEvent.click(screen.getByRole('button', { name: '启动主服务' }))
    fireEvent.click(screen.getByRole('button', { name: '确认执行' }))
    await screen.findByText('操作失败，请刷新状态后重试')
    expect(screen.queryByRole('button', { name: '确认执行' })).not.toBeInTheDocument()
    expect(api.post).toHaveBeenCalledExactlyOnceWith('/api/webui/system/service/start', { headers: { 'X-MaiBot-Service-Control': '1' } })
    expect(api.get.mock.calls.length).toBeGreaterThan(1)
  })

  it('读取失败时不允许控制服务', async () => {
    api.get.mockRejectedValue(new Error('无权限'))
    mount()
    await screen.findByText('状态读取失败：无权限')
    expect(screen.getByRole('button', { name: '启动主服务' })).toBeDisabled()
    expect(api.post).not.toHaveBeenCalled()
  })
})
