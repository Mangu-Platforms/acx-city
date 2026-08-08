import React, { useEffect, useState, useCallback, useRef } from 'react'
import { api } from '../../services/api'
import {
  Play, Pause, SkipBack, SkipForward, RotateCcw, Download,
  Volume2, Mic, BookOpen, Users, FileText, Settings, AlertTriangle, CheckCircle
} from 'lucide-react'

interface Chapter {
  index: number
  title: string
  status: string
  duration_seconds: number | null
  loudness_lufs: number | null
  qc_passed: boolean | null
  qc_issues: string[] | null
  audio_url: string | null
}

interface PipelineTrace {
  chapter_number: number
  status: string
  qa_passed: boolean | null
  agent1_ms: number | null
  agent2_ms: number | null
  agent3_ms: number | null
  agent4_ms: number | null
  agent5_ms: number | null
}

interface MultiTrackStudioProps {
  projectId: string
  jobId: string
}

type Panel = 'script' | 'characters' | 'lexicon' | 'export'

export function MultiTrackStudio({ projectId, jobId }: MultiTrackStudioProps) {
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [traces, setTraces] = useState<PipelineTrace[]>([])
  const [activeChapter, setActiveChapter] = useState(0)
  const [activePanel, setActivePanel] = useState<Panel>('script')
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(0.8)
  const [loading, setLoading] = useState(true)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const waveformRef = useRef<HTMLDivElement | null>(null)

  const fetchChapters = useCallback(async () => {
    try {
      const resp = await api.get(`/api/jobs/${jobId}`)
      setChapters(resp.data.chapters || [])
      // Also fetch pipeline traces
      try {
        const traceResp = await api.get(`/api/projects/${projectId}/pipeline/status`)
        setTraces(traceResp.data.traces || [])
      } catch {}
    } catch (err) {
      console.error('Failed to load chapters:', err)
    } finally {
      setLoading(false)
    }
  }, [jobId, projectId])

  useEffect(() => { fetchChapters() }, [fetchChapters])

  const handlePlay = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause()
      } else {
        audioRef.current.play()
      }
      setIsPlaying(!isPlaying)
    }
  }

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value)
    if (audioRef.current) {
      audioRef.current.currentTime = time
    }
    setCurrentTime(time)
  }

  const handleChapterSelect = (index: number) => {
    setActiveChapter(index)
    setIsPlaying(false)
    setCurrentTime(0)
    // Load chapter audio
    const chapter = chapters[index]
    if (chapter?.audio_url && audioRef.current) {
      audioRef.current.src = chapter.audio_url
      audioRef.current.load()
    }
  }

  const handleRerender = async (chapterIndex: number) => {
    try {
      await api.post(`/api/chapters/${chapters[chapterIndex]?.index}/rerender`, {})
      fetchChapters()
    } catch (err) {
      console.error('Failed to re-render:', err)
    }
  }

  const currentChapter = chapters[activeChapter]
  const currentTrace = traces.find(t => t.chapter_number === activeChapter + 1)

  return (
    <div className="flex h-screen flex-col bg-gray-950 text-white">
      {/* Top Bar */}
      <header className="flex items-center justify-between border-b border-gray-800 px-4 py-2">
        <div className="flex items-center gap-3">
          <BookOpen className="h-5 w-5 text-cyan-400" />
          <h1 className="text-sm font-semibold">ACX City Studio</h1>
          <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-400">
            {chapters.length} chapters
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button className="rounded p-1.5 text-gray-400 hover:bg-gray-800 hover:text-white">
            <Settings className="h-4 w-4" />
          </button>
          <button className="rounded p-1.5 text-gray-400 hover:bg-gray-800 hover:text-white">
            <Download className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left Panel — Script / Characters / Lexicon */}
        <div className="flex w-2/5 flex-col border-r border-gray-800">
          {/* Panel Tabs */}
          <div className="flex border-b border-gray-800">
            {(['script', 'characters', 'lexicon', 'export'] as Panel[]).map(panel => (
              <button
                key={panel}
                onClick={() => setActivePanel(panel)}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium capitalize ${
                  activePanel === panel
                    ? 'border-b-2 border-cyan-400 text-cyan-400'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {panel === 'script' && <FileText className="h-3.5 w-3.5" />}
                {panel === 'characters' && <Users className="h-3.5 w-3.5" />}
                {panel === 'lexicon' && <BookOpen className="h-3.5 w-3.5" />}
                {panel === 'export' && <Download className="h-3.5 w-3.5" />}
                {panel}
              </button>
            ))}
          </div>

          {/* Chapter List */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="p-4 text-center text-gray-500">Loading...</div>
            ) : chapters.length === 0 ? (
              <div className="p-4 text-center text-gray-500">No chapters yet</div>
            ) : (
              <div className="divide-y divide-gray-800">
                {chapters.map((ch, i) => (
                  <button
                    key={i}
                    onClick={() => handleChapterSelect(i)}
                    className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors ${
                      activeChapter === i ? 'bg-gray-800' : 'hover:bg-gray-900'
                    }`}
                  >
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-700 text-xs font-bold">
                      {i + 1}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="truncate text-sm font-medium">{ch.title || `Chapter ${i + 1}`}</div>
                      <div className="flex items-center gap-2 text-xs text-gray-400">
                        {ch.duration_seconds && <span>{Math.round(ch.duration_seconds)}s</span>}
                        {ch.loudness_lufs && <span>{ch.loudness_lufs.toFixed(1)} LUFS</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      {ch.qc_passed === true && <CheckCircle className="h-4 w-4 text-green-500" />}
                      {ch.qc_passed === false && <AlertTriangle className="h-4 w-4 text-amber-500" />}
                      {currentTrace?.status === 'running' && (
                        <div className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" />
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Center Panel — Waveform / Script View */}
        <div className="flex flex-1 flex-col">
          {/* Waveform Area */}
          <div className="flex-1 p-4">
            <div ref={waveformRef} className="flex h-48 items-center justify-center rounded-lg bg-gray-900 border border-gray-800">
              {currentChapter?.audio_url ? (
                <div className="text-center text-gray-500">
                  <Volume2 className="mx-auto mb-2 h-8 w-8" />
                  <p className="text-sm">Waveform visualization</p>
                  <p className="text-xs text-gray-600">WaveSurfer.js integration point</p>
                </div>
              ) : (
                <div className="text-center text-gray-500">
                  <Mic className="mx-auto mb-2 h-8 w-8" />
                  <p className="text-sm">No audio for this chapter</p>
                  <p className="text-xs text-gray-600">Generate audio to see waveform</p>
                </div>
              )}
            </div>

            {/* Script View (placeholder for panel content) */}
            {activePanel === 'script' && (
              <div className="mt-4 rounded-lg bg-gray-900 p-4">
                <h3 className="mb-3 text-sm font-semibold text-gray-300">
                  Chapter {activeChapter + 1} Script
                </h3>
                <div className="space-y-2 text-sm text-gray-400">
                  <p>Script view shows paragraph-level text with:</p>
                  <ul className="ml-4 list-disc space-y-1">
                    <li>Color-coded speaker blocks</li>
                    <li>Inline emotion tag badges</li>
                    <li>Click to override speaker/emotion</li>
                    <li>Click to re-render paragraph</li>
                  </ul>
                </div>
              </div>
            )}
          </div>

          {/* Transport Controls */}
          <div className="border-t border-gray-800 px-4 py-3">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <button onClick={() => handleChapterSelect(Math.max(0, activeChapter - 1))}
                  className="rounded p-1.5 text-gray-400 hover:text-white">
                  <SkipBack className="h-4 w-4" />
                </button>
                <button onClick={handlePlay}
                  className="rounded-full bg-cyan-600 p-2.5 text-white hover:bg-cyan-500">
                  {isPlaying ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
                </button>
                <button onClick={() => handleChapterSelect(Math.min(chapters.length - 1, activeChapter + 1))}
                  className="rounded p-1.5 text-gray-400 hover:text-white">
                  <SkipForward className="h-4 w-4" />
                </button>
              </div>

              <div className="flex flex-1 items-center gap-2">
                <span className="w-10 text-right text-xs text-gray-400">
                  {formatTime(currentTime)}
                </span>
                <input
                  type="range" min="0" max={duration || 0} step="0.1"
                  value={currentTime}
                  onChange={handleSeek}
                  className="flex-1 accent-cyan-500"
                />
                <span className="w-10 text-xs text-gray-400">
                  {formatTime(duration)}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <Volume2 className="h-4 w-4 text-gray-400" />
                <input
                  type="range" min="0" max="1" step="0.01"
                  value={volume}
                  onChange={e => setVolume(parseFloat(e.target.value))}
                  className="w-20 accent-cyan-500"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Right Panel — Voice & Export Controls */}
        <div className="flex w-1/5 flex-col border-l border-gray-800 p-4">
          <h3 className="mb-4 text-xs font-semibold uppercase text-gray-400">Chapter Controls</h3>

          {/* QC Status */}
          <div className="mb-4">
            <label className="block text-xs text-gray-500">QC Status</label>
            <div className="mt-1 flex items-center gap-2">
              {currentChapter?.qc_passed === true ? (
                <span className="flex items-center gap-1 text-sm text-green-400">
                  <CheckCircle className="h-4 w-4" /> Passed
                </span>
              ) : currentChapter?.qc_passed === false ? (
                <span className="flex items-center gap-1 text-sm text-amber-400">
                  <AlertTriangle className="h-4 w-4" /> Issues
                </span>
              ) : (
                <span className="text-sm text-gray-500">—</span>
              )}
            </div>
          </div>

          {/* Loudness */}
          {currentChapter?.loudness_lufs && (
            <div className="mb-4">
              <label className="block text-xs text-gray-500">Loudness</label>
              <div className="mt-1 text-sm">{currentChapter.loudness_lufs.toFixed(1)} LUFS</div>
            </div>
          )}

          {/* Pipeline Status */}
          {currentTrace && (
            <div className="mb-4">
              <label className="block text-xs text-gray-500">Pipeline</label>
              <div className="mt-1 text-sm capitalize">{currentTrace.status}</div>
              {currentTrace.qa_passed != null && (
                <div className={`text-xs ${currentTrace.qa_passed ? 'text-green-400' : 'text-amber-400'}`}>
                  QA: {currentTrace.qa_passed ? 'Passed' : 'Failed'}
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="mt-auto space-y-2">
            <button
              onClick={() => handleRerender(activeChapter)}
              className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-gray-800 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700"
            >
              <RotateCcw className="h-3.5 w-3.5" /> Re-render
            </button>
            <button
              className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-2 text-sm font-medium text-white hover:bg-cyan-500"
            >
              <Download className="h-3.5 w-3.5" /> Export MP3
            </button>
          </div>
        </div>
      </div>

      {/* Hidden audio element */}
      <audio
        ref={audioRef}
        onTimeUpdate={() => audioRef.current && setCurrentTime(audioRef.current.currentTime)}
        onLoadedMetadata={() => audioRef.current && setDuration(audioRef.current.duration)}
        onEnded={() => setIsPlaying(false)}
      />
    </div>
  )
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}
