import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../../services/api'
import { Mic, Upload, Play, Trash2, CheckCircle, Clock, XCircle, Shield } from 'lucide-react'

interface VoiceClone {
  id: string
  name: string
  status: 'processing' | 'ready' | 'failed'
  provider: string
  reference_duration_seconds: number
  safety_similarity_score: number | null
  created_at: string
  error?: string | null
}

interface VoiceCloneWorkbenchProps {
  organizationId: string
}

export function VoiceCloneWorkbench({ organizationId }: VoiceCloneWorkbenchProps) {
  const [clones, setClones] = useState<VoiceClone[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [cloneName, setCloneName] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [previewPlaying, setPreviewPlaying] = useState<string | null>(null)

  const fetchClones = useCallback(async () => {
    try {
      const resp = await api.get(`/voices/clones`)
      setClones(resp.data.clones ?? [])
    } catch (err) {
      console.error('Failed to load voice clones:', err)
    } finally {
      setLoading(false)
    }
  }, [organizationId])

  useEffect(() => { fetchClones() }, [fetchClones])

  const handleUpload = async () => {
    if (!selectedFile || !cloneName.trim()) return
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('audio', selectedFile)
      formData.append('name', cloneName)
      await api.post('/voices/clone', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setCloneName('')
      setSelectedFile(null)
      fetchClones()
    } catch (err) {
      console.error('Failed to create voice clone:', err)
      alert('Failed to create voice clone. Please try again.')
    } finally {
      setUploading(false)
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'ready': return <CheckCircle className="h-5 w-5 text-green-500" />
      case 'processing': return <Clock className="h-5 w-5 text-amber-500 animate-pulse" />
      case 'failed': return <XCircle className="h-5 w-5 text-red-500" />
      default: return null
    }
  }

  return (
    <div className="rounded-lg border bg-white shadow-sm">
      <div className="border-b px-6 py-4">
        <div className="flex items-center gap-2">
          <Mic className="h-5 w-5 text-rose-600" />
          <h3 className="text-lg font-semibold text-gray-900">Voice Clone Workbench</h3>
          <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-700">
            {clones.length} clones
          </span>
        </div>
        <p className="mt-1 text-sm text-gray-500">
          Upload 10–30 seconds of reference audio to create a custom voice clone.
          Uses Fish Speech S2 for 512-dimensional speaker embedding.
        </p>
      </div>

      {/* Upload Section */}
      <div className="border-b bg-rose-50 px-6 py-4">
        <h4 className="mb-3 text-sm font-semibold text-rose-900">Create New Clone</h4>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div>
            <label className="block text-xs font-medium text-gray-700">Voice Name *</label>
            <input
              value={cloneName}
              onChange={e => setCloneName(e.target.value)}
              placeholder="e.g. My Reading Voice"
              className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700">Reference Audio *</label>
            <div className="mt-1 flex items-center gap-2">
              <label className="flex cursor-pointer items-center gap-1.5 rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">
                <Upload className="h-4 w-4" />
                <span>{selectedFile ? selectedFile.name : 'Choose file'}</span>
                <input
                  type="file"
                  accept="audio/*"
                  onChange={e => setSelectedFile(e.target.files?.[0] || null)}
                  className="hidden"
                />
              </label>
            </div>
            <p className="mt-1 text-xs text-gray-400">WAV or MP3, 10–30 seconds</p>
          </div>
        </div>
        <button
          onClick={handleUpload}
          disabled={!selectedFile || !cloneName.trim() || uploading}
          className="mt-3 rounded bg-rose-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-rose-700 disabled:bg-gray-300"
        >
          {uploading ? 'Processing...' : 'Create Voice Clone'}
        </button>
      </div>

      {/* Clone List */}
      <div className="divide-y">
        {loading ? (
          <div className="px-6 py-8 text-center text-gray-500">Loading voice clones...</div>
        ) : clones.length === 0 ? (
          <div className="px-6 py-8 text-center text-gray-500">
            No voice clones yet. Upload reference audio to create your first clone.
          </div>
        ) : (
          clones.map(clone => (
            <div key={clone.id} className="flex items-center gap-4 px-6 py-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-rose-100">
                <Mic className="h-6 w-6 text-rose-600" />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-gray-900">{clone.name}</span>
                  {getStatusIcon(clone.status)}
                  <span className={`rounded px-1.5 py-0.5 text-xs ${
                    clone.status === 'ready' ? 'bg-green-100 text-green-700' :
                    clone.status === 'processing' ? 'bg-amber-100 text-amber-700' :
                    'bg-red-100 text-red-700'
                  }`}>
                    {clone.status}
                  </span>
                </div>
                <div className="mt-0.5 flex items-center gap-3 text-sm text-gray-500">
                  <span>{clone.provider}</span>
                  {clone.reference_duration_seconds > 0 && (
                    <span>{clone.reference_duration_seconds.toFixed(1)}s reference</span>
                  )}
                  {clone.safety_similarity_score != null && (
                    <span className="flex items-center gap-1">
                      <Shield className="h-3 w-3" />
                      Safety: {(clone.safety_similarity_score * 100).toFixed(0)}%
                    </span>
                  )}
                  <span className="text-gray-400">{new Date(clone.created_at).toLocaleDateString()}</span>
                </div>
                {clone.error && (
                  <div className="mt-1 text-xs text-red-500">{clone.error}</div>
                )}
              </div>
              <div className="flex items-center gap-1">
                {clone.status === 'ready' && (
                  <button
                    onClick={() => setPreviewPlaying(previewPlaying === clone.id ? null : clone.id)}
                    className="rounded p-1.5 text-gray-400 hover:bg-rose-100 hover:text-rose-600"
                    title="Preview clone"
                  >
                    <Play className="h-4 w-4" />
                  </button>
                )}
                <button
                  className="rounded p-1.5 text-gray-400 hover:bg-red-100 hover:text-red-600"
                  title="Delete clone"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Info Box */}
      <div className="border-t bg-gray-50 px-6 py-4">
        <h4 className="text-xs font-semibold text-gray-700">How Voice Cloning Works</h4>
        <ol className="mt-2 list-inside list-decimal space-y-1 text-xs text-gray-500">
          <li>Upload 10–30 seconds of clear speech (WAV or MP3)</li>
          <li>Fish Speech S2 extracts a 512-dimensional speaker embedding in &lt;3 seconds</li>
          <li>The embedding is stored as a .npy tensor in object storage</li>
          <li>The cloned voice is immediately usable for synthesis</li>
          <li>Cloned voices are org-scoped: only your organization can use them</li>
          <li>A safety check prevents cloning of protected voices</li>
        </ol>
      </div>
    </div>
  )
}
