import React, { useEffect, useState } from 'react'
import { Provider, Voice } from '../types'
import { audiobookAPI } from '../services/api'
import { Volume2, Loader, Sparkles, Cloud, Dna, X } from 'lucide-react'
import type { VoiceCitySelection } from '../types/voice-city'

interface VoiceSelectorProps {
  provider: string
  onProviderChange: (provider: string) => void
  selectedVoice: string
  onVoiceChange: (voiceId: string) => void
  engine: 'neural' | 'standard'
  onEngineChange: (engine: 'neural' | 'standard') => void
  voiceCitySelection: VoiceCitySelection | null
  onClearVoiceCity: () => void
  onOpenVoiceCity: () => void
}

export const VoiceSelector: React.FC<VoiceSelectorProps> = ({
  provider, onProviderChange, selectedVoice, onVoiceChange, engine, onEngineChange,
  voiceCitySelection, onClearVoiceCity, onOpenVoiceCity
}) => {
  const [providers, setProviders] = useState<Provider[]>([])
  const [voices, setVoices] = useState<Voice[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    audiobookAPI.getProviders()
      .then(list => {
        setProviders(list)
        if (!provider) {
          const free = list.find(p => p.available && !p.paid) || list.find(p => p.available)
          if (free) onProviderChange(free.name)
        }
      })
      .catch(e => { setError('Failed to load providers'); console.error(e) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!provider) return
    setLoading(true)
    setError(null)
    audiobookAPI.getVoices(provider, 'en')
      .then(list => {
        setVoices(list)
        if (list.length && !list.some(v => v.id === selectedVoice)) {
          onVoiceChange(list[0].id)
        }
      })
      .catch(e => { setError('Failed to load voices'); console.error(e) })
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider])

  const currentProvider = providers.find(p => p.name === provider)

  return (
    <div className="space-y-6">
      {voiceCitySelection ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-cyan-300 bg-cyan-50 p-4">
          <div className="flex items-center gap-3">
            <Dna className="h-5 w-5 text-cyan-700" />
            <div>
              <div className="font-medium text-cyan-950">{voiceCitySelection.displayName} <span className="text-xs font-semibold">V{voiceCitySelection.versionNumber}</span></div>
              <div className="text-xs text-cyan-800">Immutable Voice City identity · {voiceCitySelection.provider}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onOpenVoiceCity} className="rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-xs font-semibold text-cyan-800 hover:bg-cyan-100">Open studio</button>
            <button type="button" onClick={onClearVoiceCity} aria-label="Clear Voice City selection" className="rounded-lg border border-cyan-300 bg-white p-1.5 text-cyan-800 hover:bg-cyan-100"><X className="h-4 w-4" /></button>
          </div>
        </div>
      ) : (
        <button type="button" onClick={onOpenVoiceCity}
          className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-cyan-300 bg-cyan-50/50 px-4 py-3 text-sm font-medium text-cyan-800 transition-colors hover:bg-cyan-50">
          <Dna className="h-4 w-4" />
          <span>Design a custom narrator in Voice City</span>
        </button>
      )}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-3">Speech Engine</label>
        <div className="flex space-x-4">
          {providers.map(p => (
            <button key={p.name} type="button" disabled={!p.available}
              onClick={() => onProviderChange(p.name)}
              className={`flex-1 py-3 px-4 border rounded-lg text-center transition-colors ${
                provider === p.name ? 'border-blue-500 bg-blue-50 text-blue-700'
                : p.available ? 'border-gray-300 bg-white text-gray-700 hover:border-gray-400'
                : 'border-gray-200 bg-gray-50 text-gray-400 cursor-not-allowed'}`}>
              <div className="flex items-center justify-center space-x-2 font-medium">
                {p.paid ? <Cloud className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
                <span>{p.display_name}</span>
              </div>
              <div className="text-sm text-gray-500 mt-1">
                {p.available ? (p.paid ? 'Uses your AWS account' : 'Free, no key needed') : 'Not configured'}
              </div>
            </button>
          ))}
        </div>
      </div>

      {provider === 'polly' && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-3">Polly Engine</label>
          <div className="flex space-x-4">
            {(['neural', 'standard'] as const).map(e => (
              <button key={e} type="button" onClick={() => onEngineChange(e)}
                className={`flex-1 py-2 px-4 border rounded-lg capitalize transition-colors ${
                  engine === e ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-300 bg-white text-gray-700 hover:border-gray-400'}`}>
                {e}
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-3">Select Voice</label>
        {loading ? (
          <div className="flex items-center justify-center p-8">
            <Loader className="h-6 w-6 animate-spin text-blue-500" />
            <span className="ml-2 text-gray-600">Loading voices...</span>
          </div>
        ) : error ? (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg"><p className="text-red-700">{error}</p></div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-96 overflow-y-auto">
            {voices
              .filter(v => provider !== 'polly' || (engine === 'neural' ? v.neural : !v.neural))
              .map(voice => (
              <div key={voice.id}
                className={`p-4 border rounded-lg cursor-pointer transition-colors ${selectedVoice === voice.id ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white hover:border-gray-400'}`}
                onClick={() => onVoiceChange(voice.id)}>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium text-gray-900">{voice.name}</div>
                    <div className="text-sm text-gray-500 capitalize">{voice.gender} · {voice.language}</div>
                  </div>
                  <Volume2 className="h-5 w-5 text-gray-400" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {currentProvider && !currentProvider.paid && (
        <p className="text-xs text-gray-400">
          Free voices are provided by Microsoft Edge's read-aloud service.
        </p>
      )}
    </div>
  )
}
