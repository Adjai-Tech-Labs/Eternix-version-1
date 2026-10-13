import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { WorkspaceDialog } from '@/components/WorkspaceDialog'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    registerWorkspace: vi.fn(),
  },
}))

const registerWorkspace = vi.mocked(api.registerWorkspace)

describe('WorkspaceDialog', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <WorkspaceDialog open={false} onClose={vi.fn()} onAdded={vi.fn()} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('registers a folder path through the backend', async () => {
    registerWorkspace.mockResolvedValue({
      id: 'w1',
      name: 'Projects',
      path: '/home/user/projects',
      active: false,
      created_at: new Date().toISOString(),
    })
    const onClose = vi.fn()
    const onAdded = vi.fn()
    render(<WorkspaceDialog open={true} onClose={onClose} onAdded={onAdded} />)

    const pathInput = screen.getByPlaceholderText('/home/you/projects')
    fireEvent.change(pathInput, { target: { value: '/home/user/projects' } })
    fireEvent.click(screen.getByText('Add Workspace'))

    await waitFor(() => {
      expect(registerWorkspace).toHaveBeenCalledWith('/home/user/projects', undefined)
    })
    await waitFor(() => {
      expect(onAdded).toHaveBeenCalled()
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('shows backend validation errors', async () => {
    registerWorkspace.mockRejectedValue(new Error('Path does not exist or is not a directory: /nope'))
    render(<WorkspaceDialog open={true} onClose={vi.fn()} onAdded={vi.fn()} />)

    const pathInput = screen.getByPlaceholderText('/home/you/projects')
    fireEvent.change(pathInput, { target: { value: '/nope' } })
    fireEvent.click(screen.getByText('Add Workspace'))

    await waitFor(() => {
      expect(screen.getByText('Path does not exist or is not a directory: /nope')).toBeInTheDocument()
    })
  })
})
