import React, { useState, useEffect } from 'react'
import { FileUpload } from './components/FileUpload'
import { VoiceSelector } from './components/VoiceSelector'
import { ProgressTracker } from './components/ProgressTracker'
import { AudioPlayer } from './components/AudioPlayer'
import { audiobookAPI } from './services/api'
import { TaskStatus, SynthesisRequest, UploadResponse } from './types'
import { Book } from 'lucide-react'
import { AuthGate, LogoutButton } from './components/AuthGate'

function AudiobookApp({ userEmail, onLogout }: { userEmail?: string; onLogout: () => void }) {
  const [text, setText] = useState('')
  const [bookTitle, setBookTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [provider, setProvider] = useState('')
  const [selectedVoice, setSelectedVoice] = useState('')
  const [engine, setEngine] = useState<'neural' | 'standard'>('neural')
  const [detectedChapters, setDetectedChapters] = useState<string[]>([])
  const [currentTask, setCurrentTask] = useState<TaskStatus | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)

  useEffect(() => {
    let interval: number | undefined
    if (currentTask && (currentTask.status === 'started' || currentTask.status === 'processing')) {
      interval = window.setInterval(async () => {
        try {
          const status = await audiobookAPI.getTaskStatus(currentTask.task_id)
          setCurrentTask(status)
          if (status.status === 'completed' || status.status === 'failed') {
            setIsProcessing(false)
            window.clearInterval(interval)
          }
        } catch (e) {
          console.error('Error polling task status:', e)
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
    } catch (e) {
      console.error('Upload failed:', e)
      alert('Failed to upload file.')
    }
  }

  const handleSynthesize = async () => {
    if (!text.trim()) {
      alert('Please provide text or upload a file')
      return
    }
    try {
      setIsProcessing(true)
      const request: SynthesisRequest = {
        text, provider, voice_id: selectedVoice, engine,
        formats: ['mp3', 'm4b'], title: bookTitle, author
      }
      const response = await audiobookAPI.synthesize(request)
      setCurrentTask({ task_id: response.task_id, status: 'started', progress: 0, chapters_count: 0, current_chapter: 0 })
    } catch (e: any) {
      console.error('Start synthesis failed:', e)
      alert(e?.response?.data?.error || 'Failed to start audiobook production')
      setIsProcessing(false)
    }
  }

  const handleDownload = async (taskId: string, format: string) => {
    try {
      // The API returns a time-limited signed URL to object storage; follow it.
      const url = await audiobookAPI.getDownloadUrl(taskId, format)
      const a = document.createElement('a')
      a.href = url
      a.download = `${bookTitle || 'audiobook'}_${taskId.slice(0, 8)}.${format}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      if (format === 'mp3') setAudioUrl(url)
    } catch (e) {
      console.error('Download failed:', e)
      alert('Failed to download audiobook')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center space-x-3">
              <Book className="h-8 w-8 text-blue-600" />
              <h1 className="text-2xl font-bold text-gray-900">Audiobook Producer</h1>
            </div>
            <LogoutButton onLogout={onLogout} email={userEmail} />
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 space-y-8">
            <div className="bg-white rounded-lg shadow-sm border p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Upload Your Book</h2>
              <FileUpload onFileUpload={handleFileUpload} disabled={isProcessing} />
              {detectedChapters.length > 0 && (
                <div className="mt-4 text-sm text-gray-600">
                  <span className="font-medium">{detectedChapters.length} chapters detected:</span>{' '}
                  {detectedChapters.slice(0, 6).join(' · ')}{detectedChapters.length > 6 ? ' · …' : ''}
                </div>
              )}
            </div>

            <div className="bg-white rounded-lg shadow-sm border p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Or Paste Text</h2>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Paste your book text here, or upload a file above. Lines like 'Chapter 1' become chapter breaks."
                className="w-full h-64 p-4 border border-gray-300 rounded-lg resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={isProcessing}
              />
              {text && (
                <div className="mt-3 text-sm text-gray-500">
                  {text.length.toLocaleString()} characters • {text.split(/\s+/).length.toLocaleString()} words
                </div>
              )}
            </div>

            <div className="bg-white rounded-lg shadow-sm border p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Book Details</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <input value={bookTitle} onChange={e => setBookTitle(e.target.value)}
                  placeholder="Book title (used in M4B metadata)" disabled={isProcessing}
                  className="p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent" />
                <input value={author} onChange={e => setAuthor(e.target.value)}
                  placeholder="Author (optional)" disabled={isProcessing}
                  className="p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent" />
              </div>
            </div>

            <div className="bg-white rounded-lg shadow-sm border p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Voice Settings</h2>
              <VoiceSelector
                provider={provider}
                onProviderChange={setProvider}
                selectedVoice={selectedVoice}
                onVoiceChange={setSelectedVoice}
                engine={engine}
                onEngineChange={setEngine}
              />
            </div>

            <button
              onClick={handleSynthesize}
              disabled={!text.trim() || !selectedVoice || isProcessing}
              className="w-full py-4 px-6 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              {isProcessing ? 'Generating Audiobook...' : 'Generate Audiobook'}
            </button>
          </div>

          <div className="space-y-8">
            {currentTask && (
              <div className="bg-white rounded-lg shadow-sm border p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">Production Status</h2>
                <ProgressTracker taskStatus={currentTask} onDownload={handleDownload} />
              </div>
            )}

            {audioUrl && (
              <div className="bg-white rounded-lg shadow-sm border p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">Audio Preview</h2>
                <AudioPlayer audioUrl={audioUrl} />
              </div>
            )}

            <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
              <h3 className="font-semibold text-blue-900 mb-3">How It Works</h3>
              <ol className="text-sm text-blue-800 space-y-2 list-decimal list-inside">
                <li>Upload a DOCX/TXT/PDF or paste text — chapters are detected automatically</li>
                <li>Pick a voice (Edge voices are free, Polly uses your AWS account)</li>
                <li>Generate — unchanged text is reused from cache on re-runs</li>
                <li>Download MP3, or M4B with real chapter markers for audiobook apps</li>
              </ol>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <AuthGate>
      {(auth, logout) => <AudiobookApp userEmail={auth.user?.email} onLogout={logout} />}
    </AuthGate>
  )
}
