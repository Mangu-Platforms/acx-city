import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../../services/api'
import { Users, Plus, Trash2, Volume2, Sliders, ChevronDown } from 'lucide-react'

interface CharacterVoice {
  id: string
  character_name: string
  voice_id: string | null
  voice_slug: string | null
  pitch_adjustment: number
  speed_adjustment: number
  base_emotion: string
  is_narrator: boolean
  attribution_confidence: number | null
  notes: string | null
}

interface CharacterPanelProps {
  projectId: string
}

const EMOTIONS = ['neutral', 'angry', 'sad', 'whisper', 'soft', 'breathy', 'excited', 'embarrassed']
const VOICE_SLUGS = [
  'en-US-AriaNeural', 'en-US-JennyNeural', 'en-US-GuyNeural',
  'en-GB-SoniaNeural', 'en-GB-RyanNeural', 'en-AU-NatashaNeural',
  'en-US-AmberNeural', 'en-US-AnaNeural', 'en-US-AndrewNeural',
  'en-US-BrandonNeural', 'en-US-ChristopherNeural', 'en-US-CoraNeural',
  'en-US-DavisNeural', 'en-US-ElizabethNeural', 'en-US-EricNeural',
]

export function CharacterPanel({ projectId }: CharacterPanelProps) {
  const [characters, setCharacters] = useState<CharacterVoice[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [newChar, setNewChar] = useState({
    character_name: '', voice_slug: 'en-US-AriaNeural', base_emotion: 'neutral',
    pitch_adjustment: 1.0, speed_adjustment: 1.0, is_narrator: false,
  })
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const fetchCharacters = useCallback(async () => {
    try {
      const resp = await api.get(`/api/projects/${projectId}/characters`)
      setCharacters(resp.data)
    } catch (err) {
      console.error('Failed to load characters:', err)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { fetchCharacters() }, [fetchCharacters])

  const handleAdd = async () => {
    if (!newChar.character_name.trim()) return
    try {
      await api.post(`/api/projects/${projectId}/characters`, newChar)
      setNewChar({ character_name: '', voice_slug: 'en-US-AriaNeural', base_emotion: 'neutral', pitch_adjustment: 1.0, speed_adjustment: 1.0, is_narrator: false })
      setShowAdd(false)
      fetchCharacters()
    } catch (err) {
      console.error('Failed to add character:', err)
    }
  }

  const handleUpdate = async (char: CharacterVoice, updates: Partial<CharacterVoice>) => {
    try {
      await api.post(`/api/projects/${projectId}/characters`, { ...char, ...updates })
      fetchCharacters()
    } catch (err) {
      console.error('Failed to update character:', err)
    }
  }

  const narrator = characters.find(c => c.is_narrator)
  const otherCharacters = characters.filter(c => !c.is_narrator)

  return (
    <div className="rounded-lg border bg-white shadow-sm">
      <div className="border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users className="h-5 w-5 text-cyan-600" />
            <h3 className="text-lg font-semibold text-gray-900">Character Voice Bible</h3>
            <span className="rounded-full bg-cyan-100 px-2 py-0.5 text-xs font-medium text-cyan-700">
              {characters.length} characters
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowAdd(!showAdd)}
              className="flex items-center gap-1 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-700"
            >
              <Plus className="h-4 w-4" /> Add Character
            </button>
            <button
              className="flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              title="Export Voice Bible as JSON"
            >
              <Download className="h-4 w-4" /> Export
            </button>
          </div>
        </div>
      </div>

      {showAdd && (
        <div className="border-b bg-cyan-50 px-6 py-4">
          <h4 className="mb-3 text-sm font-semibold text-cyan-900">Add Character</h4>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-gray-700">Character Name *</label>
              <input
                value={newChar.character_name}
                onChange={e => setNewChar({ ...newChar, character_name: e.target.value })}
                placeholder="e.g. Sarah"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Voice</label>
              <select
                value={newChar.voice_slug}
                onChange={e => setNewChar({ ...newChar, voice_slug: e.target.value })}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
              >
                {VOICE_SLUGS.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Base Emotion</label>
              <select
                value={newChar.base_emotion}
                onChange={e => setNewChar({ ...newChar, base_emotion: e.target.value })}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
              >
                {EMOTIONS.map(e => <option key={e} value={e}>{e}</option>)}
              </select>
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <button onClick={handleAdd} disabled={!newChar.character_name.trim()}
              className="rounded bg-cyan-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-cyan-700 disabled:bg-gray-300">
              Add Character
            </button>
            <button onClick={() => setShowAdd(false)}
              className="rounded border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="divide-y">
        {loading ? (
          <div className="px-6 py-8 text-center text-gray-500">Loading characters...</div>
        ) : characters.length === 0 ? (
          <div className="px-6 py-8 text-center text-gray-500">
            No characters assigned yet. Run the pipeline to auto-detect characters, or add them manually.
          </div>
        ) : (
          <>
            {narrator && <CharacterRow key={narrator.id} char={narrator} expanded={expandedId === narrator.id}
              onToggle={() => setExpandedId(expandedId === narrator.id ? null : narrator.id)}
              onUpdate={(updates) => handleUpdate(narrator, updates)} />}
            {otherCharacters.map(char => (
              <CharacterRow key={char.id} char={char} expanded={expandedId === char.id}
                onToggle={() => setExpandedId(expandedId === char.id ? null : char.id)}
                onUpdate={(updates) => handleUpdate(char, updates)} />
            ))}
          </>
        )}
      </div>
    </div>
  )
}

function CharacterRow({ char, expanded, onToggle, onUpdate }: {
  char: CharacterVoice; expanded: boolean; onToggle: () => void;
  onUpdate: (updates: Partial<CharacterVoice>) => void
}) {
  return (
    <div className="px-6 py-3">
      <div className="flex items-center gap-3 cursor-pointer" onClick={onToggle}>
        <div className={`h-3 w-3 rounded-full ${char.is_narrator ? 'bg-slate-500' : 'bg-cyan-500'}`} />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-gray-900">{char.character_name}</span>
            {char.is_narrator && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">narrator</span>}
            {char.attribution_confidence != null && (
              <span className={`rounded px-1.5 py-0.5 text-xs ${
                char.attribution_confidence > 0.8 ? 'bg-green-100 text-green-700' :
                char.attribution_confidence > 0.5 ? 'bg-amber-100 text-amber-700' :
                'bg-red-100 text-red-700'
              }`}>
                {Math.round(char.attribution_confidence * 100)}% confidence
              </span>
            )}
          </div>
          <div className="text-sm text-gray-500">{char.voice_slug || 'No voice assigned'} · {char.base_emotion}</div>
        </div>
        <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </div>
      {expanded && (
        <div className="mt-3 grid grid-cols-1 gap-3 rounded-lg bg-gray-50 p-4 md:grid-cols-2">
          <div>
            <label className="block text-xs font-medium text-gray-700">Voice</label>
            <select value={char.voice_slug || ''} onChange={e => onUpdate({ voice_slug: e.target.value })}
              className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
              <option value="">None</option>
              {VOICE_SLUGS.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700">Base Emotion</label>
            <select value={char.base_emotion} onChange={e => onUpdate({ base_emotion: e.target.value })}
              className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
              {EMOTIONS.map(e => <option key={e} value={e}>{e}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700">Pitch: {char.pitch_adjustment.toFixed(2)}</label>
            <input type="range" min="0.5" max="2" step="0.05" value={char.pitch_adjustment}
              onChange={e => onUpdate({ pitch_adjustment: parseFloat(e.target.value) })}
              className="mt-1 w-full" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700">Speed: {char.speed_adjustment.toFixed(2)}</label>
            <input type="range" min="0.5" max="2" step="0.05" value={char.speed_adjustment}
              onChange={e => onUpdate({ speed_adjustment: parseFloat(e.target.value) })}
              className="mt-1 w-full" />
          </div>
          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-gray-700">Notes</label>
            <input value={char.notes || ''} onChange={e => onUpdate({ notes: e.target.value })}
              placeholder="Character notes..."
              className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
          </div>
        </div>
      )}
    </div>
  )
}

function Download(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/>
      <line x1="12" x2="12" y1="15" y2="3"/>
    </svg>
  )
}
