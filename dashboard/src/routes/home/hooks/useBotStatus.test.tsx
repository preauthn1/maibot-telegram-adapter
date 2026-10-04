import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { backendApi } from '@/lib/http'
import { useBotStatus } from './useBotStatus'

vi.mock('@/lib/http', () => ({ backendApi: { get: vi.fn() } }))

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('真实主服务状态', () => {
  it.each([
    ['inactive', 'dead', '0', false],
    ['active', 'running', '123', true],
    ['active', 'exited', '0', false],
    ['activating', 'start', '123', false],
  ])('%s / %s 不使用 WebUI 的 running=true 和 uptime', async (ActiveState, SubState, MainPID, running) => {
    vi.mocked(backendApi.get).mockImplementation((path) => Promise.resolve(
      path.endsWith('/service')
        ? { ActiveState, SubState, MainPID }
        : { running: true, uptime: 9999, version: '1', start_time: '2026-01-01' }
    ) as never)
    const { result } = renderHook(() => useBotStatus())
    await act(async () => { await result.current.fetchBotStatus(true) })
    expect(result.current.botStatus?.running).toBe(running)
    expect(result.current.botStatus?.uptime).toBeNull()
  })

  it('服务接口不可用时显示未知，不把历史 active 缓存继续作为当前在线证据', async () => {
    vi.mocked(backendApi.get).mockImplementation((path) => path.endsWith('/service')
      ? Promise.reject(new Error('未启用 systemd 控制'))
      : Promise.resolve({ running: true, uptime: 9999, version: '1', start_time: '' }) as never)
    const { result } = renderHook(() => useBotStatus())
    await act(async () => { await result.current.fetchBotStatus(true) })
    expect(result.current.botStatus?.running).toBeNull()
    expect(result.current.botStatus?.uptime).toBeNull()
  })
})
