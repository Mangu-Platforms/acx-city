import React from 'react'
import { Book, Dna, Mic, Users, BookOpen, Activity, Library } from 'lucide-react'

type Page = 'production' | 'voice-city' | 'voices' | 'clone' | 'studio'

interface NavigationProps {
  current: Page
  onNavigate: (page: Page) => void
  projectId?: string
}

const NAV_ITEMS: { id: Page; label: string; icon: React.ReactNode }[] = [
  { id: 'production', label: 'Production', icon: <Book className="h-4 w-4" /> },
  { id: 'voice-city', label: 'Voice City', icon: <Dna className="h-4 w-4 text-cyan-300" /> },
  { id: 'voices', label: 'Voice Catalog', icon: <Library className="h-4 w-4" /> },
  { id: 'clone', label: 'Voice Clone', icon: <Mic className="h-4 w-4" /> },
  { id: 'studio', label: 'Studio', icon: <Activity className="h-4 w-4" /> },
]

export function Navigation({ current, onNavigate, projectId }: NavigationProps) {
  return (
    <nav className="flex items-center gap-1">
      {NAV_ITEMS.map(item => (
        <button
          key={item.id}
          onClick={() => onNavigate(item.id)}
          disabled={item.id === 'studio' && !projectId}
          className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
            current === item.id
              ? 'bg-blue-100 text-blue-700'
              : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
          } disabled:cursor-not-allowed disabled:opacity-50`}
        >
          {item.icon}
          {item.label}
        </button>
      ))}
    </nav>
  )
}
