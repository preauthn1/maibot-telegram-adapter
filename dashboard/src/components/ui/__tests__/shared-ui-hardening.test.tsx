import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MultiSelect } from '../multi-select'
import { Button } from '../button'
import { Input } from '../input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../tabs'
import { AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogTitle } from '../alert-dialog'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../dialog'

afterEach(cleanup)

describe('共享 UI 交互边界', () => {
  it('长内容控件提供收缩、换行和错误状态样式，保留调用方覆盖', () => {
    render(<><Button>很长的操作名称</Button><Input aria-label="名称" aria-invalid className="h-12" /></>)
    expect(screen.getByRole('button')).toHaveClass('whitespace-normal', 'min-h-9')
    expect(screen.getByRole('textbox')).toHaveClass('min-w-0', 'aria-invalid:border-destructive', 'h-12')
  })
  it('对话框限制动态视口高度并保留关闭触摸目标', () => {
    render(<Dialog open><DialogContent><DialogTitle>编辑</DialogTitle><DialogDescription>长说明</DialogDescription></DialogContent></Dialog>)
    expect(screen.getByRole('dialog')).toHaveClass('max-h-[calc(100dvh-2rem)]')
    expect(screen.getByRole('button', { name: '关闭' })).toHaveClass('h-9', 'w-9')
  })
  it('警告对话框长内容可滚动且不占满手机宽度', () => {
    render(<AlertDialog open><AlertDialogContent><AlertDialogTitle>确认</AlertDialogTitle><AlertDialogDescription>长说明</AlertDialogDescription></AlertDialogContent></AlertDialog>)
    expect(screen.getByRole('alertdialog')).toHaveClass('overflow-y-auto', 'max-h-[calc(100dvh-2rem)]', 'w-[calc(100vw-2rem)]')
  })
  it('下拉内容限制可用宽度且完整换行选项', () => {
    render(<Select open defaultValue="long"><SelectTrigger aria-label="模型"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="long">长模型名称</SelectItem></SelectContent></Select>)
    expect(screen.getByRole('combobox', { hidden: true })).toHaveClass('min-w-0')
    expect(screen.getByRole('option')).toHaveClass('whitespace-normal', '[overflow-wrap:anywhere]')
    expect(document.querySelector('[data-dashboard-select-content]')).toHaveStyle({ maxWidth: 'min(var(--radix-select-content-available-width, 100vw), calc(100vw - 2rem))' })
  })
  it('表格滚动容器支持键盘聚焦并保留表头语义', () => {
    render(<Table aria-label="模型列表"><TableHeader><TableRow><TableHead>模型</TableHead></TableRow></TableHeader><TableBody><TableRow><TableCell>长标识符</TableCell></TableRow></TableBody></Table>)
    expect(document.querySelector('[data-dashboard-table-wrapper]')).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('columnheader')).toHaveAttribute('scope', 'col')
    expect(screen.getByRole('cell')).toHaveClass('[overflow-wrap:anywhere]')
  })
  it('页签支持窄屏滚动并保留 Radix 面板关系', () => {
    render(<Tabs defaultValue="one"><TabsList><TabsTrigger value="one">第一项</TabsTrigger><TabsTrigger value="two" disabled>第二项</TabsTrigger></TabsList><TabsContent value="one">内容</TabsContent></Tabs>)
    expect(screen.getByRole('tablist')).toHaveClass('max-w-full', 'overflow-x-auto')
    expect(screen.getByRole('tab', { name: '第一项' })).toHaveAttribute('aria-controls', screen.getByRole('tabpanel').id)
    expect(screen.getByRole('tab', { name: '第二项' })).toBeDisabled()
  })
  it('多选删除控件有独立名称，禁用时不进入键盘序列', () => {
    const { rerender } = render(<MultiSelect options={[{ value: 'a', label: '模型 A' }]} selected={['a']} onChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: '移除 模型 A' })).toHaveAttribute('tabindex', '0')
    rerender(<MultiSelect options={[{ value: 'a', label: '模型 A' }]} selected={['a']} onChange={vi.fn()} disabled />)
    expect(screen.getByRole('button', { name: '移除 模型 A' })).toHaveAttribute('tabindex', '-1')
  })
  it('禁用或忙碌确认按钮不会被回车触发', () => {
    const confirm = vi.fn()
    render(<Dialog open><DialogContent confirmOnEnter><DialogTitle>编辑</DialogTitle><DialogDescription>说明</DialogDescription><Button data-dialog-action="confirm" aria-disabled="true" onClick={confirm}>确认</Button></DialogContent></Dialog>)
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Enter' })
    expect(confirm).not.toHaveBeenCalled()
  })
  it('对话框回车确认不抢占其它按钮的键盘操作', () => {
    const confirm = vi.fn()
    render(
      <Dialog open>
        <DialogContent confirmOnEnter>
          <DialogTitle>编辑</DialogTitle>
          <DialogDescription>测试键盘确认边界</DialogDescription>
          <Button>其它操作</Button>
          <Button data-dialog-action="confirm" onClick={confirm}>确认</Button>
        </DialogContent>
      </Dialog>
    )
    fireEvent.keyDown(screen.getByRole('button', { name: '其它操作' }), { key: 'Enter' })
    expect(confirm).not.toHaveBeenCalled()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Enter' })
    expect(confirm).toHaveBeenCalledOnce()
  })
})
