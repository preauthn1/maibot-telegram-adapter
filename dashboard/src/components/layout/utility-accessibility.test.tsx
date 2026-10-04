import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { BackToTop } from '../back-to-top'
import { RoutePendingFallback } from '../route-pending-fallback'

vi.mock('@tanstack/react-router', () => ({ useRouterState: () => '/settings' }))

function scrollable(id: string) {
  const element = document.createElement('div')
  element.id = id
  Object.defineProperties(element, {
    clientHeight: { value: 300 },
    scrollHeight: { value: 1200 },
    scrollTop: { value: 500, writable: true },
  })
  element.scrollTo = vi.fn()
  document.body.appendChild(element)
  return element
}

describe('布局辅助控件可访问性', () => {
  it('隐藏回顶按钮不能进入 Tab 顺序，嵌套滚动不能劫持主滚动区', () => {
    const main = scrollable('main-content')
    const nested = scrollable('nested-list')
    const { container } = render(<BackToTop />)
    const button = container.querySelector('button')!
    expect(button).toHaveAttribute('tabindex', '-1')
    fireEvent.scroll(nested)
    expect(button).toHaveAttribute('aria-hidden', 'true')
    fireEvent.scroll(main)
    expect(screen.getByRole('button', { name: '回到顶部' })).toHaveAttribute('tabindex', '0')
    fireEvent.scroll(nested)
    fireEvent.click(button)
    expect(main.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
    expect(nested.scrollTo).not.toHaveBeenCalled()
    main.remove()
    nested.remove()
  })

  it('页面等待保留中文状态及减少动态效果样式', () => {
    const { container } = render(<RoutePendingFallback />)
    expect(screen.getByRole('status')).toHaveAccessibleName('加载中')
    expect(container.firstElementChild).toHaveAttribute('aria-busy', 'true')
    expect(container.firstElementChild).toHaveClass('[&_.animate-bounce]:motion-reduce:animate-none')
  })
})
