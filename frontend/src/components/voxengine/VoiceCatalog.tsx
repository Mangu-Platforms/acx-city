import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { api } from '../../services/api';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface StockVoice {
  id: string;
  display_name: string;
  provider: 'edge' | 'polly' | 'kokoro';
  gender: 'male' | 'female' | 'neutral';
  accent: string;
  age_range: string;
  languages: string[];
  style_tags: string[];
  emotion_tags: string[];
  sample_url?: string;
}

interface VoiceCatalogProps {
  onSelect: (voice: StockVoice) => void;
  selectedVoiceId?: string;
}

type ViewMode = 'grid' | 'list';

interface Filters {
  search: string;
  gender: string;
  accent: string;
  age_range: string;
  provider: string;
}

const PAGE_SIZE = 50;

// ─── Accent Options ──────────────────────────────────────────────────────────

const ACCENTS = [
  'american',
  'british',
  'australian',
  'indian',
  'irish',
  'scottish',
  'south african',
  'canadian',
  'new zealander',
  'singaporean',
];

const AGE_RANGES = ['child', 'teen', 'young-adult', 'adult', 'senior'];

const PROVIDERS: StockVoice['provider'][] = ['edge', 'polly', 'kokoro'];

const GENDER_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'neutral', label: 'Neutral' },
];

// ─── Badge Component ─────────────────────────────────────────────────────────

const Badge: React.FC<{
  label: string;
  variant?: 'default' | 'gender' | 'accent' | 'tag' | 'emotion';
}> = ({ label, variant = 'default' }) => {
  const base = 'inline-block px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap';
  const variantClasses: Record<string, string> = {
    default: 'bg-gray-700 text-gray-200',
    gender: label === 'male'
      ? 'bg-blue-900/60 text-blue-300'
      : label === 'female'
        ? 'bg-pink-900/60 text-pink-300'
        : 'bg-purple-900/60 text-purple-300',
    accent: 'bg-teal-900/60 text-teal-300',
    tag: 'bg-amber-900/50 text-amber-300',
    emotion: 'bg-rose-900/50 text-rose-300',
  };
  return <span className={`${base} ${variantClasses[variant]}`}>{label}</span>;
};

// ─── Voice Card ──────────────────────────────────────────────────────────────

const VoiceCard: React.FC<{
  voice: StockVoice;
  viewMode: ViewMode;
  isSelected: boolean;
  onSelect: () => void;
  onPreview: () => void;
  isPreviewPlaying: boolean;
}> = ({ voice, viewMode, isSelected, onSelect, onPreview, isPreviewPlaying }) => {
  const selectedRing = isSelected ? 'ring-2 ring-indigo-500' : 'ring-1 ring-gray-700';

  if (viewMode === 'grid') {
    return (
      <div
        className={`relative flex flex-col gap-3 p-4 rounded-xl bg-gray-800/60 ${selectedRing} hover:ring-indigo-400 transition-all`}
      >
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-gray-100 truncate">
              {voice.display_name}
            </h3>
            <span className="text-xs text-gray-400">{voice.provider}</span>
          </div>
          <Badge label={voice.gender} variant="gender" />
        </div>

        {/* Accent & Age */}
        <div className="flex flex-wrap gap-1.5">
          <Badge label={voice.accent} variant="accent" />
          {voice.age_range && <Badge label={voice.age_range} />}
        </div>

        {/* Style Tags */}
        {voice.style_tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {voice.style_tags.slice(0, 4).map((tag) => (
              <Badge key={tag} label={tag} variant="tag" />
            ))}
            {voice.style_tags.length > 4 && (
              <span className="text-xs text-gray-500">+{voice.style_tags.length - 4}</span>
            )}
          </div>
        )}

        {/* Emotion Tags */}
        {voice.emotion_tags && voice.emotion_tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {voice.emotion_tags.slice(0, 3).map((tag) => (
              <Badge key={tag} label={tag} variant="emotion" />
            ))}
            {voice.emotion_tags.length > 3 && (
              <span className="text-xs text-gray-500">+{voice.emotion_tags.length - 3}</span>
            )}
          </div>
        )}

        {/* Languages */}
        <div className="flex flex-wrap gap-1">
          {voice.languages.map((lang) => (
            <span key={lang} className="text-xs text-gray-500">{lang}</span>
          ))}
        </div>

        {/* Actions */}
        <div className="flex gap-2 mt-auto pt-2">
          <button
            onClick={onPreview}
            disabled={isPreviewPlaying}
            className="flex-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-200 disabled:opacity-50 transition-colors"
          >
            {isPreviewPlaying ? '▶ Playing…' : '▶ Preview'}
          </button>
          <button
            onClick={onSelect}
            className={`flex-1 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              isSelected
                ? 'bg-indigo-600 text-white'
                : 'bg-indigo-600/20 text-indigo-300 hover:bg-indigo-600/40'
            }`}
          >
            {isSelected ? '✓ Selected' : 'Select'}
          </button>
        </div>
      </div>
    );
  }

  // ── List view ──────────────────────────────────────────────────────────────
  return (
    <div
      className={`flex items-center gap-4 px-4 py-3 rounded-lg bg-gray-800/40 ${selectedRing} hover:ring-indigo-400 transition-all`}
    >
      <div className="flex-1 min-w-0 grid grid-cols-[1fr_auto_auto_auto_auto] items-center gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-gray-100 truncate">{voice.display_name}</h3>
          <span className="text-xs text-gray-400">{voice.provider}</span>
        </div>
        <Badge label={voice.gender} variant="gender" />
        <Badge label={voice.accent} variant="accent" />
        <div className="flex flex-wrap gap-1 max-w-[200px]">
          {voice.style_tags.slice(0, 2).map((tag) => (
            <Badge key={tag} label={tag} variant="tag" />
          ))}
        </div>
        <div className="flex flex-wrap gap-1">
          {voice.emotion_tags?.slice(0, 2).map((tag) => (
            <Badge key={tag} label={tag} variant="emotion" />
          ))}
        </div>
      </div>

      <div className="flex gap-2 shrink-0">
        <button
          onClick={onPreview}
          disabled={isPreviewPlaying}
          className="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-200 disabled:opacity-50 transition-colors"
        >
          {isPreviewPlaying ? '▶ Playing…' : '▶ Preview'}
        </button>
        <button
          onClick={onSelect}
          className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
            isSelected
              ? 'bg-indigo-600 text-white'
              : 'bg-indigo-600/20 text-indigo-300 hover:bg-indigo-600/40'
          }`}
        >
          {isSelected ? '✓ Selected' : 'Select'}
        </button>
      </div>
    </div>
  );
};

// ─── Main Component ──────────────────────────────────────────────────────────

export const VoiceCatalog: React.FC<VoiceCatalogProps> = ({ onSelect, selectedVoiceId }) => {
  // State
  const [voices, setVoices] = useState<StockVoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [page, setPage] = useState(1);
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const [filters, setFilters] = useState<Filters>({
    search: '',
    gender: '',
    accent: '',
    age_range: '',
    provider: '',
  });

  // ── Fetch voices ───────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const params = new URLSearchParams();
        if (filters.gender) params.set('gender', filters.gender);
        if (filters.accent) params.set('accent', filters.accent);
        if (filters.age_range) params.set('age_range', filters.age_range);
        if (filters.provider) params.set('provider', filters.provider);
        if (filters.search) params.set('q', filters.search);

        const res = await api.get(`/api/voices?${params.toString()}`);
        if (!cancelled) setVoices(res.data ?? []);
      } catch (err: any) {
        if (!cancelled) setError(err?.message ?? 'Failed to load voices');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filters.gender, filters.accent, filters.age_range, filters.provider, filters.search]);

  // ── Client-side filter for search (server also filters, but this adds instant feedback) ──

  const filtered = useMemo(() => {
    const q = filters.search.toLowerCase().trim();
    if (!q) return voices;
    return voices.filter(
      (v) =>
        v.display_name.toLowerCase().includes(q) ||
        v.accent.toLowerCase().includes(q) ||
        v.style_tags.some((t) => t.toLowerCase().includes(q)) ||
        v.emotion_tags?.some((t) => t.toLowerCase().includes(q)),
    );
  }, [voices, filters.search]);

  // ── Pagination ─────────────────────────────────────────────────────────────

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paged = useMemo(
    () => filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
    [filtered, safePage],
  );

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [filters]);

  // ── Preview ────────────────────────────────────────────────────────────────

  const handlePreview = useCallback((voice: StockVoice) => {
    // Stop current playback
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }

    const url = voice.sample_url ?? `/api/voices/${voice.id}/sample`;
    const audio = new Audio(url);
    audioRef.current = audio;

    setPreviewingId(voice.id);

    // Stop after 5 seconds
    const timer = setTimeout(() => {
      audio.pause();
      audio.currentTime = 0;
      setPreviewingId(null);
    }, 5000);

    audio.addEventListener('ended', () => {
      clearTimeout(timer);
      setPreviewingId(null);
    });

    audio.addEventListener('error', () => {
      clearTimeout(timer);
      setPreviewingId(null);
    });

    audio.play().catch(() => {
      clearTimeout(timer);
      setPreviewingId(null);
    });
  }, []);

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      audioRef.current?.pause();
    };
  }, []);

  // ── Filter helpers ─────────────────────────────────────────────────────────

  const updateFilter = useCallback(<K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-4 h-full text-gray-100">
      {/* ── Toolbar ───────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px]">
          <input
            type="text"
            placeholder="Search voices…"
            value={filters.search}
            onChange={(e) => updateFilter('search', e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm rounded-lg bg-gray-800 border border-gray-700 focus:border-indigo-500 focus:outline-none placeholder-gray-500"
          />
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
        </div>

        {/* Gender */}
        <select
          value={filters.gender}
          onChange={(e) => updateFilter('gender', e.target.value)}
          className="px-3 py-2 text-sm rounded-lg bg-gray-800 border border-gray-700 focus:border-indigo-500 focus:outline-none"
        >
          {GENDER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        {/* Accent */}
        <select
          value={filters.accent}
          onChange={(e) => updateFilter('accent', e.target.value)}
          className="px-3 py-2 text-sm rounded-lg bg-gray-800 border border-gray-700 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">All Accents</option>
          {ACCENTS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        {/* Age Range */}
        <select
          value={filters.age_range}
          onChange={(e) => updateFilter('age_range', e.target.value)}
          className="px-3 py-2 text-sm rounded-lg bg-gray-800 border border-gray-700 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">All Ages</option>
          {AGE_RANGES.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        {/* Provider */}
        <select
          value={filters.provider}
          onChange={(e) => updateFilter('provider', e.target.value)}
          className="px-3 py-2 text-sm rounded-lg bg-gray-800 border border-gray-700 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">All Providers</option>
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>

        {/* View Toggle */}
        <div className="flex rounded-lg overflow-hidden border border-gray-700">
          <button
            onClick={() => setViewMode('grid')}
            className={`px-3 py-2 text-sm ${
              viewMode === 'grid' ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'
            }`}
            title="Grid view"
          >
            ▦
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`px-3 py-2 text-sm ${
              viewMode === 'list' ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'
            }`}
            title="List view"
          >
            ☰
          </button>
        </div>
      </div>

      {/* ── Result count ──────────────────────────────────────────────────── */}
      <div className="text-xs text-gray-500">
        {loading ? 'Loading…' : `${filtered.length} voice${filtered.length !== 1 ? 's' : ''} found`}
      </div>

      {/* ── Error ─────────────────────────────────────────────────────────── */}
      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-900/30 border border-red-700 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* ── Voice Grid / List ─────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-500">
            <div className="animate-spin w-6 h-6 border-2 border-gray-600 border-t-indigo-500 rounded-full mr-3" />
            Loading voices…
          </div>
        ) : paged.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-gray-500">No voices match your filters.</div>
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {paged.map((voice) => (
              <VoiceCard
                key={voice.id}
                voice={voice}
                viewMode={viewMode}
                isSelected={voice.id === selectedVoiceId}
                onSelect={() => onSelect(voice)}
                onPreview={() => handlePreview(voice)}
                isPreviewPlaying={previewingId === voice.id}
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {paged.map((voice) => (
              <VoiceCard
                key={voice.id}
                voice={voice}
                viewMode={viewMode}
                isSelected={voice.id === selectedVoiceId}
                onSelect={() => onSelect(voice)}
                onPreview={() => handlePreview(voice)}
                isPreviewPlaying={previewingId === voice.id}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Pagination ────────────────────────────────────────────────────── */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2 border-t border-gray-800">
          <button
            disabled={safePage <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="px-3 py-1.5 text-sm rounded-lg bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ← Prev
          </button>
          {Array.from({ length: totalPages }, (_, i) => i + 1)
            .filter(
              (p) =>
                p === 1 ||
                p === totalPages ||
                (p >= safePage - 2 && p <= safePage + 2),
            )
            .reduce<(number | 'ellipsis')[]>((acc, p, idx, arr) => {
              if (idx > 0 && p - (arr[idx - 1] as number) > 1) acc.push('ellipsis');
              acc.push(p);
              return acc;
            }, [])
            .map((item, idx) =>
              item === 'ellipsis' ? (
                <span key={`e-${idx}`} className="px-1 text-gray-600">
                  …
                </span>
              ) : (
                <button
                  key={item}
                  onClick={() => setPage(item as number)}
                  className={`w-8 h-8 text-sm rounded-lg transition-colors ${
                    item === safePage
                      ? 'bg-indigo-600 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  {item}
                </button>
              ),
            )}
          <button
            disabled={safePage >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            className="px-3 py-1.5 text-sm rounded-lg bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
};

export default VoiceCatalog;
