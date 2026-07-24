import React, { useRef, useEffect } from 'react'
import { Play, Pause, Volume2 } from 'lucide-react'

interface Props { audioUrl: string }

export const AudioPlayer: React.FC<Props> = ({ audioUrl }) => {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [isPlaying, setIsPlaying] = React.useState(false)
  const [progress, setProgress] = React.useState(0)
  const [volume, setVolume] = React.useState(1)

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    const update = () => setProgress((audio.currentTime / audio.duration) * 100 || 0)
    const ended = () => setIsPlaying(false)
    audio.addEventListener('timeupdate', update)
    audio.addEventListener('ended', ended)
    return () => {
      audio.removeEventListener('timeupdate', update)
      audio.removeEventListener('ended', ended)
    }
  }, [])

  const toggle = () => {
    const audio = audioRef.current; if (!audio) return
    if (isPlaying) audio.pause(); else audio.play()
    setIsPlaying(!isPlaying)
  }
  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const audio = audioRef.current; if (!audio) return
    const rect = e.currentTarget.getBoundingClientRect()
    const percent = (e.clientX - rect.left) / rect.width
    audio.currentTime = percent * audio.duration
    setProgress(percent * 100)
  }
  const setVol = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = parseFloat(e.target.value)
    setVolume(v); if (audioRef.current) audioRef.current.volume = v
  }

  return (
    <div className="bg-white border border-gray-300 rounded-lg p-4 space-y-4">
      <audio ref={audioRef} src={audioUrl} />
      <div className="w-full bg-gray-200 rounded-full h-2 cursor-pointer" onClick={seek}>
        <div className="bg-blue-600 h-2 rounded-full transition-all" style={{ width: `${progress}%` }} />
      </div>
      <div className="flex items-center justify-between">
        <button onClick={toggle} className="flex items-center justify-center w-12 h-12 bg-blue-600 text-white rounded-full hover:bg-blue-700 transition-colors">
          {isPlaying ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
        </button>
        <div className="flex items-center space-x-3 flex-1 max-w-xs ml-4">
          <Volume2 className="h-5 w-5 text-gray-500" />
          <input type="range" min="0" max="1" step="0.1" value={volume} onChange={setVol} className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer slider" />
        </div>
      </div>
    </div>
  )
}
