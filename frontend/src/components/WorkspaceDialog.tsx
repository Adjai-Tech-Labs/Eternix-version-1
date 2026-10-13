import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Card, CardTitle } from '@/components/ui/Card'
import { FolderPlus, X, Loader2 } from 'lucide-react'
import { api } from '@/api/client'

interface WorkspaceDialogProps {
  open: boolean
  onClose: () => void
  onAdded: () => void
}

export function WorkspaceDialog({ open, onClose, onAdded }: WorkspaceDialogProps) {
  const [path, setPath] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (!open) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = path.trim()
    if (!trimmed || submitting) return

    setSubmitting(true)
    setError(null)
    try {
      await api.registerWorkspace(trimmed, name.trim() || undefined)
      // A freshly added folder becomes the workspace the agent uses.
      try {
        await api.setActiveWorkspace(trimmed)
      } catch {
        // Activation is best-effort; the folder is still registered.
      }
      setPath('')
      setName('')
      onAdded()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add workspace')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={e => {
        if (e.target === e.currentTarget) onClose()
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Add workspace folder"
    >
      <Card variant="elevated" className="w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <CardTitle className="flex items-center gap-2">
            <FolderPlus className="w-5 h-5 text-eternix-400" />
            Add Workspace Folder
          </CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <X className="w-4 h-4" />
          </Button>
        </div>

        <p className="text-sm text-eternix-400 mb-4">
          Register a folder from this machine. The agent can read and work with
          files inside registered workspaces.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            label="Folder path"
            value={path}
            onChange={e => setPath(e.target.value)}
            placeholder="/home/you/projects"
            error={error ?? undefined}
            helperText="Absolute path of the folder on this machine"
            autoFocus
          />
          <Input
            label="Name (optional)"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="My Project"
            helperText="Defaults to the folder name"
          />

          {error && (
            <p className="text-xs text-eternix-500">
              The path is validated by the backend — it must exist on this machine.
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!path.trim() || submitting}>
              {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
              Add Workspace
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
