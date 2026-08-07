import React, { useEffect, useState } from 'react'
import { FileUpload } from './components/FileUpload'
import { VoiceSelector } from './components/VoiceSelector'
import { ProgressTracker } from './components/ProgressTracker'
import { AudioPlayer } from './components/AudioPlayer'
import { VoiceCityStudio } from './components/voice-city/VoiceCityStudio'
import { VoiceCatalog, VoiceCloneWorkbench, LexiconEditor, CharacterPanel, MultiTrackStudio } from './components/voxengine'
import { Navigation } from './components/Navigation'
import { audiobookAPI } from './services/api'
import { TaskStatus, SynthesisRequest, UploadResponse } from './types'
import type { VoiceCitySelection } from './types/voice-city'
import { Book, Dna } from 'lucide-react'
import { AuthGate, LogoutButton } from './components/AuthGate'

type Workspace = 'production' | 'voice-city' | 'voices' | 'clone' | 'studio' | 'lexicon' | 'characters'
const ACTIVE_STATUSES = new Set(['started', 'processing', 'queued', 'running'])
const TERMINAL_STATUSES = new Set(['completed', 'succeeded', 'needs_review', 'failed', 'canceled'])

function AudiobookApp({ userEmail, onLogout }: { userEmail?: string; onLogout: () => void }) {
  const [workspace, setWorkspace] = useState<Workspace>('production')
  const [text, setText] = useState('')
  const [bookTitle, setBookTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [provider, setProvider] = useState('')
  const [selectedVoice, setSelectedVoice] = useState('')
  const [voiceCitySelection, setVoiceCitySelection] = useState<VoiceCitySelection | null>(null)
  const [engine, setEngine] = useState<'neural' | 'standard'>('neural')
  const [detectedChapters, setDetectedChapters] = useState<string[]>([])
  const [currentTask, setCurrentTask] = useState<TaskStatus | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)

  useEffect(() => {
    let interval: number | undefined
    if (currentTask && ACTIVE_STATUSES.has(currentTask.status)) {
      interval = window.setInterval(async () => {
        try {
          const status = await audiobookAPI.getTaskStatus(currentTask.task_id)
          setCurrentTask(status)
          if (TERMINAL_STATUSES.has(status.status)) {
            setIsProcessing(false)
            window.clearInterval(interval)
          }
        } catch (error) {
          console.error('Error polling task status:', error)
        }
      }, 2000)
    }
    return () => { if (interval) window.clearInterval(interval) }
  }, [currentTask])

  const handleFileUpload = async (file: File) => {
    try {
      const result: UploadResponse = await audiobookAPI.uploadFile(file)
      setText(result.text)
      setDetectedChapters(result.detected_chapters || [])
      if (!bookTitle) setBookTitle(file.name.replace(/\.[^.]+$/, ''))
    } catch (error) {
      console.error('Upload failed:', error)
      window.alert('Failed to upload file.')
    }
  }

  const handleVoiceCitySelection = (selection: VoiceCitySelection) => {
    setVoiceCitySelection(selection)
    setProvider(selection.provider)
    setSelectedVoice(selection.providerVoiceId)
    setEngine('neural')
    setWorkspace('production')
  }

  const handleSynthesize = async () => {
    if (!text.trim()) {
      window.alert('Please provide text or upload a file')
      return
    }
    try {
      setIsProcessing(true)
      const request: SynthesisRequest = {
        text,
        provider,
        voice_id: selectedVoice,
        engine,
        formats: ['mp3', 'm4b'],
        title: bookTitle,
        author,
        voice_version_id: voiceCitySelection?.voiceVersionId,
        voice_direction: voiceCitySelection?.directionPlan,
      }
      const response = await audiobookAPI.synthesize(request)
      setCurrentTask({ task_id: response.task_id, status: response.status as TaskStatus['status'], progress: 0, chapters_count: 0, current_chapter: 0, voice_version_id: voiceCitySelection?.voiceVersionId, voice_display_name: voiceCitySelection?.displayName })
    } catch (error: any) {
      console.error('Start synthesis failed:', error)
      window.alert(error?.response?.data?.error || 'Failed to start audiobook production')
      setIsProcessing(false)
    }
  }

  const handleDownload = async (taskId: string, format: string) => {
    try {
      const url = await audiobookAPI.getDownloadUrl(taskId, format)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${bookTitle || 'audiobook'}_${taskId.slice(0, 8)}.${format}`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      if (format === 'mp3') setAudioUrl(url)
    } catch (error) {
      console.error('Download failed:', error)
      window.alert('Failed to download audiobook')
    }
  }

  if (workspace === 'voice-city') {
    return <VoiceCityStudio manuscriptText={text} onUseVoice={handleVoiceCitySelection} onReturnToProduction={() => setWorkspace('production')} />
  }

  if (workspace === 'voices') {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="border-b bg-white shadow-sm">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex h-16 items-center justify-between gap-4">
              <Navigation current={workspace} onNavigate={(p) => setWorkspace(p as Workspace)} />
              <LogoutButton onLogout={onLogout} email={userEmail} />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <VoiceCatalog onSelect={(v) => { setProvider(v.provider); setSelectedVoice(v.provider_voice_id || ''); setWorkspace('production') }} />
        </main>
      </div>
    )
  }

  if (workspace === 'clone') {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="border-b bg-white shadow-sm">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex h-16 items-center justify-between gap-4">
              <Navigation current={workspace} onNavigate={(p) => setWorkspace(p as Workspace)} />
              <LogoutButton onLogout={onLogout} email={userEmail} />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <VoiceCloneWorkbench organizationId={''} />
        </main>
      </div>
    )
  }

  if (workspace === 'studio') {
    return (
      <MultiTrackStudio projectId={''} jobId={currentTask?.task_id || ''} />
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white shadow-sm">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-16 items-center justify-between gap-4">
            <div className="flex items-center space-x-3">
              <Book className="h-8 w-8 text-blue-600" />
              <h1 className="text-xl font-bold text-gray-900 sm:text-2xl">Audiobook Producer</h1>
            </div>
            <Navigation current={workspace} onNavigate={(p) => setWorkspace(p as Workspace)} />
            <LogoutButton onLogout={onLogout} email={userEmail} />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {voiceCitySelection && <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-3"><div className="flex items-center gap-3"><Dna className="h-5 w-5 text-cyan-700" /><div><strong className="text-sm text-cyan-950">{voiceCitySelection.displayName} V{voiceCitySelection.versionNumber}</strong><p className="text-xs text-cyan-800">Immutable Voice City version selected{voiceCitySelection.directionPlan?.cast.length ? ` with ${voiceCitySelection.directionPlan.cast.length} character cast assignment${voiceCitySelection.directionPlan.cast.length === 1 ? '' : 's'}` : ''}.</p></div></div><button type="button" onClick={() => setWorkspace('voice-city')} className="rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-xs font-semibold text-cyan-800">Open studio</button></div>}

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
          <div className="space-y-8 lg:col-span-2">
            <div className="rounded-lg border bg-white p-6 shadow-sm">
              <h2 className="mb-4 text-lg font-semibold text-gray-900">Upload Your Book</h2>
              <FileUpload onFileUpload={handleFileUpload} disabled={isProcessing} />
              {detectedChapters.length > 0 && <div className="mt-4 text-sm text-gray-600"><span className="font-medium">{detectedChapters.length} chapters detected:</span>{' '}{detectedChapters.slice(0, 6).join(' · ')}{detectedChapters.length > 6 ? ' · …' : ''}</div>}
            </div>

            <div className="rounded-lg border bg-white p-6 shadow-sm">
              <h2 className="mb-4 text-lg font-semibold text-gray-900">Or Paste Text</h2>
              <textarea value={text} onChange={event => setText(event.target.value)} placeholder="Paste your book text here, or upload a file above. Lines like 'Chapter 1' become chapter breaks." className="h-64 w-full resize-none rounded-lg border border-gray-300 p-4 focus:border-transparent focus:ring-2 focus:ring-blue-500" disabled={isProcessing} />
              {text && <div className="mt-3 text-sm text-gray-500">{text.length.toLocaleString()} characters • {text.split(/\s+/).length.toLocaleString()} words</div>}
            </div>

            <div className="rounded-lg border bg-white p-6 shadow-sm">
              <h2 className="mb-4 text-lg font-semibold text-gray-900">Book Details</h2>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <input value={bookTitle} onChange={event => setBookTitle(event.target.value)} placeholder="Book title (used in M4B metadata)" disabled={isProcessing} className="rounded-lg border border-gray-300 p-3 focus:border-transparent focus:ring-2 focus:ring-blue-500" />
                <input value={author} onChange={event => setAuthor(event.target.value)} placeholder="Author (optional)" disabled={isProcessing} className="rounded-lg border border-gray-300 p-3 focus:border-transparent focus:ring-2 focus:ring-blue-500" />
              </div>
            </div>

            <div className="rounded-lg border bg-white p-6 shadow-sm">
              <h2 className="mb-4 text-lg font-semibold text-gray-900">Voice Settings</h2>
              <VoiceSelector
                provider={provider}
                onProviderChange={setProvider}
                selectedVoice={selectedVoice}
                onVoiceChange={setSelectedVoice}
                engine={engine}
                onEngineChange={setEngine}
                voiceCitySelection={voiceCitySelection}
                onClearVoiceCity={() => setVoiceCitySelection(null)}
                onOpenVoiceCity={() => setWorkspace('voice-city')}
              />
            </div>

            <button onClick={handleSynthesize} disabled={!text.trim() || !selectedVoice || isProcessing} className="w-full rounded-lg bg-blue-600 px-6 py-4 font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-400">{isProcessing ? 'Generating Audiobook…' : voiceCitySelection ? `Generate with ${voiceCitySelection.displayName} V${voiceCitySelection.versionNumber}` : 'Generate Audiobook'}</button>
          </div>

          <div className="space-y-8">
            {currentTask && <div className="rounded-lg border bg-white p-6 shadow-sm"><h2 className="mb-4 text-lg font-semibold text-gray-900">Production Status</h2>{currentTask.voice_display_name && <p className="mb-3 rounded-lg bg-cyan-50 px-3 py-2 text-xs text-cyan-800">Voice: {currentTask.voice_display_name}</p>}<ProgressTracker taskStatus={currentTask} onDownload={handleDownload} /></div>}
            {audioUrl && <div className="rounded-lg border bg-white p-6 shadow-sm"><h2 className="mb-4 text-lg font-semibold text-gray-900">Audio Preview</h2><AudioPlayer audioUrl={audioUrl} /></div>}
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-6"><h3 className="mb-3 font-semibold text-blue-900">How It Works</h3><ol className="list-inside list-decimal space-y-2 text-sm text-blue-800"><li>Upload a DOCX/TXT/PDF or paste text</li><li>Choose a catalog voice or a versioned Voice City identity</li><li>Generate with durable jobs and content-addressed caching</li><li>Download MP3 or chaptered M4B after quality control</li></ol></div>
          </div>
        </div>
      </main>
    </div>
  )
}

export default function App() {
  return <AuthGate>{(auth, logout) => <AudiobookApp userEmail={auth.user?.email} onLogout={logout} />}</AuthGate>
}
