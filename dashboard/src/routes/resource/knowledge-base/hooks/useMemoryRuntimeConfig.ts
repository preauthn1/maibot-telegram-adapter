/**
 * useMemoryRuntimeConfig —— 长期记忆「运行时配置」领域 hook（页面逻辑下沉切片）。
 *
 * 收编运行时状态相关的服务端状态与交互：
 * - 运行时配置（runtimeConfig）走 useQuery，默认即拉取（enabled: true）——它服务于概览区/图谱，
 *   原页面在初始化时加载，而非懒加载；
 * - 自检刷新（refreshSelfCheck）：触发后端自检并重拉运行时配置，结果走全局 toast；
 * - 向量重建预览-执行用 usePendingOperation：openVectorRebuildDialog 拉 dry-run 预览（setVectorRebuildPreview）
 *   后 submit，confirm 执行真重建并重拉运行时配置。
 *
 * 读失败本由 loadPage/initial effect 弹 toast；迁移后由 useQuery error + 局部 errorText 呈现
 *   （查询读失败遵循 query.ts 约定不弹全局 toast），写操作（自检/重建）保留原中文 toast 文案。
 */
import { useCallback, useMemo, useState } from 'react'

import { useQuery, useQueryClient } from '@tanstack/react-query'

import { useToast } from '@/hooks/use-toast'
import { usePendingOperation, type UsePendingOperationResult } from '@/hooks/usePendingOperation'
import {
  getMemoryRuntimeConfig,
  rebuildMemoryRuntimeVectors,
  refreshMemoryRuntimeSelfCheck,
  type MemoryRuntimeConfigPayload,
  type MemoryRuntimeOperationState,
} from '@/lib/memory-api'

/** 拒绝 disabled/skipped/unready 的成功空操作；不把 success 当作健康结论。 */
function runtimeOperationBlockReason(payload: MemoryRuntimeOperationState): string | null {
  if (payload.skipped === true || payload.outcome === 'disabled' || payload.disabled === true ||
    payload.enabled === false || payload.memory_enabled === false || payload.retrieval_mode === 'disabled') {
    return '记忆系统禁用或操作被跳过，没有执行请求。'
  }
  if (payload.runtime_ready === false) return '记忆运行时尚未就绪，没有确认请求已执行。'
  return null
}

/** 向量重建待定操作的载荷：dry-run 预览已暂存，confirm 时执行真重建（无额外参数） */
interface VectorRebuildOperation {
  preview: Record<string, number> | null
}

export interface UseMemoryRuntimeConfigResult {
  runtimeConfig: MemoryRuntimeConfigPayload | null
  /** 运行时配置首次加载中（用于页面整体 loading 门控） */
  runtimeLoading: boolean
  /** 运行时配置读取错误文案（查询失败时局部呈现） */
  runtimeErrorText: string
  /** 重新拉取运行时配置（外部写操作后刷新概览区） */
  refreshRuntimeConfig: () => Promise<void>

  refreshingCheck: boolean
  refreshSelfCheck: () => Promise<void>

  vectorRebuildDialogOpen: boolean
  setVectorRebuildDialogOpen: (open: boolean) => void
  vectorRebuildPreview: Record<string, number> | null
  vectorRebuilding: boolean
  openVectorRebuildDialog: () => Promise<void>
  confirmVectorRebuild: () => Promise<void>
}

export function useMemoryRuntimeConfig(): UseMemoryRuntimeConfigResult {
  const { toast } = useToast()
  const queryClient = useQueryClient()

  // 运行时配置：服务于概览区/图谱，默认即拉取（沿用原页面初始化时加载、非懒加载的时机）
  const runtimeQuery = useQuery({
    queryKey: ['memory-runtime', 'config'],
    queryFn: () => getMemoryRuntimeConfig(),
  })
  const runtimeConfig = runtimeQuery.data ?? null
  const runtimeErrorText = runtimeQuery.error
    ? runtimeQuery.error instanceof Error
      ? runtimeQuery.error.message
      : '加载长期记忆运行状态失败'
    : ''

  const refreshRuntimeConfig = useCallback(async () => {
    await runtimeQuery.refetch()
  }, [runtimeQuery])

  const setRuntimeConfig = useCallback(
    (next: MemoryRuntimeConfigPayload) => {
      queryClient.setQueryData(['memory-runtime', 'config'], next)
    },
    [queryClient]
  )

  const [refreshingCheck, setRefreshingCheck] = useState(false)
  const refreshSelfCheck = useCallback(async () => {
    try {
      setRefreshingCheck(true)
      const payload = await refreshMemoryRuntimeSelfCheck()
      const nextRuntime = await getMemoryRuntimeConfig()
      setRuntimeConfig(nextRuntime)
      const blockReason = runtimeOperationBlockReason(payload)
      const skipped = blockReason !== null
      const reportHealthy = payload.report?.ok === true
      const runtimeHealthy = nextRuntime.runtime_ready === true && nextRuntime.retrieval_ready === true &&
        nextRuntime.memory_enabled !== false && nextRuntime.embedding_degraded !== true
      const healthy = payload.success && !skipped && reportHealthy && runtimeHealthy
      const disabledOrSkipped = blockReason !== null ? blockReason :
        !payload.success ? (payload.error ?? '处理器未成功完成自检。') :
        !reportHealthy ? '处理器返回成功，但自检报告未确认健康。' :
        !runtimeHealthy ? '自检报告返回成功，但运行时尚未就绪。' : '自检报告与运行时状态均正常。'
      toast({
        title: healthy ? '自检通过' : skipped ? '自检未执行' : '自检未通过',
        description: disabledOrSkipped,
        variant: healthy ? 'default' : 'destructive',
      })
    } catch (error) {
      toast({
        title: '运行时自检失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setRefreshingCheck(false)
    }
  }, [setRuntimeConfig, toast])

  // 向量重建预览-执行：用通用待定模块缓冲「dry-run 预览 → 对话框确认 → 真重建」
  const [vectorRebuildDialogOpen, setVectorRebuildDialogOpenState] = useState(false)
  const [vectorRebuildPreview, setVectorRebuildPreview] = useState<Record<string, number> | null>(
    null
  )
  const [vectorRebuilding, setVectorRebuilding] = useState(false)

  const vectorRebuildPendingOp: UsePendingOperationResult<VectorRebuildOperation> =
    usePendingOperation<VectorRebuildOperation>({
      onConfirm: async () => {
        try {
          setVectorRebuilding(true)
          const payload = await rebuildMemoryRuntimeVectors({ dry_run: false })
          const nextRuntime = await getMemoryRuntimeConfig()
          setRuntimeConfig(nextRuntime)
          const blockReason = runtimeOperationBlockReason(payload)
          const skipped = blockReason !== null
          const handlerSucceeded = payload.success && !skipped && (payload.failed ?? 0) === 0
          const reportHealthy = payload.self_check?.ok === true
          const runtimeHealthy = nextRuntime.runtime_ready === true && nextRuntime.retrieval_ready === true &&
            nextRuntime.memory_enabled !== false && nextRuntime.embedding_degraded !== true
          const healthy = handlerSucceeded && reportHealthy && runtimeHealthy
          const detail = skipped
            ? (blockReason ?? '记忆运行时操作未执行。')
            : healthy
              ? `处理器完成、自检报告与运行时健康均确认：已处理 ${payload.done ?? 0} 条。`
              : payload.success
                ? `处理器返回成功，但运行时或自检未确认健康（已处理 ${payload.done ?? 0} 条，失败 ${payload.failed ?? 0} 条）。`
                : (payload.error ?? `向量重建失败（已处理 ${payload.done ?? 0} 条，失败 ${payload.failed ?? 0} 条）。`)
          setVectorRebuildDialogOpenState(false)
          toast({
            title: healthy ? '向量重建完成' : skipped ? '向量重建未执行' : '向量重建未完全成功',
            description: detail,
            variant: healthy ? 'default' : 'destructive',
          })
        } catch (error) {
          toast({
            title: '向量重建失败',
            description: error instanceof Error ? error.message : '未知错误',
            variant: 'destructive',
          })
        } finally {
          setVectorRebuilding(false)
        }
      },
    })

  const openVectorRebuildDialog = useCallback(async () => {
    try {
      setVectorRebuildDialogOpenState(true)
      setVectorRebuildPreview(null)
      vectorRebuildPendingOp.cancel()
      const payload = await rebuildMemoryRuntimeVectors({ dry_run: true })
      const blockReason = runtimeOperationBlockReason(payload)
      if (blockReason) throw new Error(blockReason)
      if (!payload.success || payload.dry_run !== true || !payload.counts) {
        throw new Error(payload.error ?? '后端未返回可执行的向量重建预览')
      }
      const preview = payload.counts
      setVectorRebuildPreview(preview)
      // 预览完成后暂存待定操作，进入等待确认态
      vectorRebuildPendingOp.submit({ preview })
    } catch (error) {
      setVectorRebuildDialogOpenState(false)
      vectorRebuildPendingOp.cancel()
      toast({
        title: '读取向量重建预览失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    }
  }, [toast, vectorRebuildPendingOp])

  const confirmVectorRebuild = useCallback(async () => {
    await vectorRebuildPendingOp.confirm()
  }, [vectorRebuildPendingOp])

  // 对话框关闭时同步放弃待定操作，保持 dialogOpen 与 pending 一致
  const setVectorRebuildDialogOpen = useCallback(
    (open: boolean) => {
      setVectorRebuildDialogOpenState(open)
      if (!open) {
        vectorRebuildPendingOp.cancel()
        setVectorRebuildPreview(null)
      }
    },
    [vectorRebuildPendingOp]
  )

  return useMemo(
    () => ({
      runtimeConfig,
      runtimeLoading: runtimeQuery.isLoading,
      runtimeErrorText,
      refreshRuntimeConfig,
      refreshingCheck,
      refreshSelfCheck,
      vectorRebuildDialogOpen,
      setVectorRebuildDialogOpen,
      vectorRebuildPreview,
      vectorRebuilding,
      openVectorRebuildDialog,
      confirmVectorRebuild,
    }),
    [
      runtimeConfig,
      runtimeQuery.isLoading,
      runtimeErrorText,
      refreshRuntimeConfig,
      refreshingCheck,
      refreshSelfCheck,
      vectorRebuildDialogOpen,
      setVectorRebuildDialogOpen,
      vectorRebuildPreview,
      vectorRebuilding,
      openVectorRebuildDialog,
      confirmVectorRebuild,
    ]
  )
}
