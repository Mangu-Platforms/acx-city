import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../../services/api'
import { BookOpen, Plus, Trash2, Volume2, Search, Download, Upload } from 'lucide-react'

interface LexiconEntry {
  id: string
  word: string
  ipa_phoneme: string | null
  phonetic_spelling: string | null
  context_note: string | null
  source: string
  is_global: boolean
}

interface LexiconEditorProps {
  projectId: string
}

export function LexiconEditor({ projectId }: LexiconEditorProps) {
  const [entries, setEntries] = useState<LexiconEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [newEntry, setNewEntry] = useState({ word: '', ipa_phoneme: '', phonetic_spelling: '', context_note: '' })
  const [testingWord, setTestingWord] = useState<string | null>(null)

  const fetchEntries = useCallback(async () => {
    try {
      const resp = await api.get(`/v1/projects/${projectId}/lexicon`)
      setEntries(resp.data)
    } catch (err) {
      console.error('Failed to load lexicon:', err)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { fetchEntries() }, [fetchEntries])

  const handleAdd = async () => {
    if (!newEntry.word.trim()) return
    try {
      await api.post(`/v1/projects/${projectId}/lexicon`, newEntry)
      setNewEntry({ word: '', ipa_phoneme: '', phonetic_spelling: '', context_note: '' })
      setShowAdd(false)
      fetchEntries()
    } catch (err) {
      console.error('Failed to add entry:', err)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this pronunciation entry?')) return
    try {
      await api.delete(`/v1/projects/${projectId}/lexicon/${id}`)
      fetchEntries()
    } catch (err) {
      console.error('Failed to delete entry:', err)
    }
  }

  const handleTest = async (word: string) => {
    setTestingWord(word)
    // TODO: Call preview synthesis endpoint
    setTimeout(() => setTestingWord(null), 2000)
  }

  const filtered = entries.filter(e =>
    e.word.toLowerCase().includes(searchTerm.toLowerCase()) ||
    e.ipa_phoneme?.toLowerCase().includes(searchTerm.toLowerCase())
  )

  return (
    <div className="rounded-lg border bg-white shadow-sm">
      <div className="border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-purple-600" />
            <h3 className="text-lg font-semibold text-gray-900">Pronunciation Lexicon</h3>
            <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
              {entries.length} entries
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowAdd(!showAdd)}
              className="flex items-center gap-1 rounded-lg bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700"
            >
              <Plus className="h-4 w-4" /> Add Entry
            </button>
          </div>
        </div>

        <div className="mt-3 flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Search words or IPA..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-4 text-sm focus:border-purple-500 focus:ring-1 focus:ring-purple-500"
            />
          </div>
        </div>
      </div>

      {showAdd && (
        <div className="border-b bg-purple-50 px-6 py-4">
          <h4 className="mb-3 text-sm font-semibold text-purple-900">Add Pronunciation Entry</h4>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-gray-700">Word *</label>
              <input
                value={newEntry.word}
                onChange={e => setNewEntry({ ...newEntry, word: e.target.value })}
                placeholder="e.g. Hermione"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">IPA Phoneme</label>
              <input
                value={newEntry.ipa_phoneme}
                onChange={e => setNewEntry({ ...newEntry, ipa_phoneme: e.target.value })}
                placeholder="e.g. /hɜːrˈmaɪ.əni/"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm font-mono"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Phonetic Spelling</label>
              <input
                value={newEntry.phonetic_spelling}
                onChange={e => setNewEntry({ ...newEntry, phonetic_spelling: e.target.value })}
                placeholder="e.g. her-MY-uh-nee"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700">Context Note</label>
              <input
                value={newEntry.context_note}
                onChange={e => setNewEntry({ ...newEntry, context_note: e.target.value })}
                placeholder="e.g. character name, Book 1"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
              />
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <button
              onClick={handleAdd}
              disabled={!newEntry.word.trim()}
              className="rounded bg-purple-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:bg-gray-300"
            >
              Add Entry
            </button>
            <button
              onClick={() => setShowAdd(false)}
              className="rounded border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="divide-y">
        {loading ? (
          <div className="px-6 py-8 text-center text-gray-500">Loading lexicon...</div>
        ) : filtered.length === 0 ? (
          <div className="px-6 py-8 text-center text-gray-500">
            {searchTerm ? 'No matching entries found.' : 'No pronunciation entries yet. Add words that need special pronunciation.'}
          </div>
        ) : (
          filtered.map(entry => (
            <div key={entry.id} className="flex items-center gap-4 px-6 py-3 hover:bg-gray-50">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-gray-900">{entry.word}</span>
                  {entry.source === 'auto' && (
                    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">auto-suggested</span>
                  )}
                  {entry.is_global && (
                    <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-700">global</span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-3 text-sm text-gray-600">
                  {entry.ipa_phoneme && <span className="font-mono">{entry.ipa_phoneme}</span>}
                  {entry.phonetic_spelling && <span className="text-gray-400">({entry.phonetic_spelling})</span>}
                  {entry.context_note && <span className="text-gray-400 italic">{entry.context_note}</span>}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleTest(entry.word)}
                  className="rounded p-1.5 text-gray-400 hover:bg-purple-100 hover:text-purple-600"
                  title="Test pronunciation"
                >
                  <Volume2 className={`h-4 w-4 ${testingWord === entry.word ? 'animate-pulse text-purple-600' : ''}`} />
                </button>
                <button
                  onClick={() => handleDelete(entry.id)}
                  className="rounded p-1.5 text-gray-400 hover:bg-red-100 hover:text-red-600"
                  title="Delete entry"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
