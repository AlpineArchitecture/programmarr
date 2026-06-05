const BASE = '/api';

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...opts?.headers },
    ...opts,
  });
  if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
  return res.json();
}

export const api = {
  getConfig: () => req<Record<string, string>>('/config'),
  saveConfig: (data: Record<string, string>) =>
    req('/config', { method: 'POST', body: JSON.stringify(data) }),
  getConfigStatus: () =>
    req<{ configured: boolean; has_tmdb: boolean; has_auth: boolean }>('/config/status'),

  getStatus: () =>
    req<{ tunarr: ConnStatus; plex: ConnStatus }>('/status'),
  getTunarrChannels: () => req<TunarrChannel[]>('/tunarr/channels'),

  getChannels: () => req<ChannelsFile>('/channels'),
  updateChannels: (data: object) =>
    req('/channels', { method: 'PUT', body: JSON.stringify(data) }),
  getChannel: (n: number) => req<Channel>(`/channels/${n}`),
  updateChannel: (n: number, ch: object) =>
    req(`/channels/${n}`, { method: 'PUT', body: JSON.stringify(ch) }),
  deleteChannel: (n: number) => req(`/channels/${n}`, { method: 'DELETE' }),
  getLibraryTitles: () => req<string[]>('/library/titles'),

  getCsvInfo: () => req<CsvInfo>('/pipeline/csv/info'),
  getFacets: (minItems = 5) => req<LibraryFacets>(`/pipeline/facets?min_items=${minItems}`),
  getPrompt: (target?: string, prefs?: string, start?: number) => {
    const p = new URLSearchParams();
    if (target) p.set('target', target);
    if (prefs) p.set('preferences', prefs);
    if (start !== undefined && start !== 10) p.set('start', String(start));
    return req<{ content: string }>(`/pipeline/prompt?${p}`);
  },
  buildPrompt: (opts: PromptOptions) =>
    req<{ content: string }>('/pipeline/prompt', {
      method: 'POST',
      body: JSON.stringify(opts),
    }),
  composeChannels: (specs: CandidateSpec[], start: number) =>
    req<ComposeResult>('/pipeline/compose', {
      method: 'POST',
      body: JSON.stringify({ specs, start }),
    }),
  validateText: async (content: string) => {
    const form = new FormData();
    form.append('content', content);
    const res = await fetch(`${BASE}/pipeline/validate`, { method: 'POST', body: form });
    return res.json() as Promise<ValidateResult>;
  },
  validateFile: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${BASE}/pipeline/validate`, { method: 'POST', body: form });
    return res.json() as Promise<ValidateResult>;
  },

  getLogs: () => req<LogEntry[]>('/logs'),
  getLog: (name: string) => req<{ name: string; content: string }>(`/logs/${name}`),

  getLibraries: () => req<PlexLibrary[]>('/pipeline/libraries'),
  getCollections: () => req<PlexCollection[]>('/pipeline/collections'),
  applyCollections: (selections: CollectionSelection[]) =>
    req<{ ok: boolean; added: number }>('/pipeline/collections/apply', {
      method: 'POST',
      body: JSON.stringify(selections),
    }),

  // ── Live channels (recipes) ──
  previewRecipe: (value: string, order?: string | null, exclude: string[] = []) =>
    req<RecipePreview>('/recipes/preview', {
      method: 'POST',
      body: JSON.stringify({ value, order, exclude }),
    }),
  getRecipesStatus: () => req<RecipesStatus>('/recipes/status'),
  runRecipes: (apply: boolean, only?: number) =>
    req<CycleSummary>(
      `/recipes/run?apply=${apply}${only !== undefined ? `&only=${only}` : ''}`,
      { method: 'POST' },
    ),
  pauseRecipes: (paused: boolean) =>
    req<RecipesStatus>(`/recipes/pause?paused=${paused}`, { method: 'POST' }),
  saveRecipeConfig: (enabled: boolean, interval_hours: number) =>
    req<RecipesStatus>('/recipes/config', {
      method: 'POST',
      body: JSON.stringify({ enabled, interval_hours }),
    }),
};

// ── Types ──────────────────────────────────────────────────────────────────────

export interface ConnStatus { ok: boolean; url: string; error?: string }
export interface TunarrChannel { number: number; name: string; id?: string }
export interface MatchRef { match: 'title_contains'; value: string; order?: string | null; exclude?: string[] }
export type ContentItem = string | { collection: string } | MatchRef;
export function isMatchRef(c: ContentItem): c is MatchRef {
  return typeof c === 'object' && c !== null && 'match' in c;
}
export function isCollectionRef(c: ContentItem): c is { collection: string } {
  return typeof c === 'object' && c !== null && 'collection' in c;
}
export interface Channel {
  number: number;
  name: string;
  shuffle: 'ordered' | 'shuffle' | 'block';
  content: ContentItem[];
  live?: boolean;
}

// ── Live channels (recipes) ──
export interface RecipeMatch { title: string; year: number | null }
export interface RecipePreview { value: string; order: string | null; count: number; matches: RecipeMatch[] }
export interface CycleChange { number: number; name: string; added: string[]; added_count: number; removed_count: number; applied: boolean }
export interface CycleSkip { number: number; name: string; reason: string }
export interface CycleSummary {
  time: string; apply: boolean; live: number; changed: number;
  changes: CycleChange[]; skipped: CycleSkip[]; error: string | null;
}
export interface ChannelSyncState { checked_at?: string; changed_at?: string; change_summary?: string }
export interface RecipesStatus {
  enabled: boolean; paused: boolean; running: boolean;
  interval_hours: number; next_run_seconds: number | null;
  live_count: number; last_cycle: CycleSummary | null;
  channels: Record<string, ChannelSyncState>;
}
export interface ChannelsFile { channels: Channel[]; orphaned: string[]; suggested_channels: string[] }
export interface CsvInfo {
  exists: boolean;
  rows?: number;
  size?: number;
  modified?: number;
  preview?: string[];
  movies?: number;
  tv_shows?: number;
  skipped_movies?: number;
  skipped_shows?: number;
}
export interface ValidateResult { ok: boolean; count?: number; error?: string; channels?: Channel[] }

// ── Planner facets + prompt options ──
export interface GenreFacet { display: string; tag: string; count: number }
export interface DecadeFacet { label: string; start: number; end: number; count: number }
export interface GenreDecadeFacet { genre: string; display: string; decade_start: number; decade_label: string; count: number }
export interface BlendFacet { genres: string[]; displays: string[]; count: number }
export interface EntityFacet { value: string; count: number }
export interface TvGenreFacet { genre: string; count: number }
export interface MarathonFacet { title: string; episodes: number; seasons: number }
export interface LibraryFacets {
  exists: boolean;
  movies?: number;
  tv_shows?: number;
  marathon_count?: number;
  min_items?: number;
  genres?: { canonical: GenreFacet[]; more: GenreFacet[] };
  decades?: DecadeFacet[];
  genre_decade?: GenreDecadeFacet[];
  blends?: BlendFacet[];
  studios?: EntityFacet[];
  directors?: EntityFacet[];
  actors?: EntityFacet[];
  tv_genres?: TvGenreFacet[];
  marathons?: MarathonFacet[];
}

// ── Planner v2 candidate composition ──
export type CandidateKind =
  | 'genre' | 'genre_decade' | 'blend' | 'studio' | 'director' | 'actor' | 'tv_genre' | 'marathon';
export interface CandidateSpec {
  kind: CandidateKind;
  name?: string;
  genre?: string;
  genres?: string[];
  decade_start?: number;
  value?: string;
  shuffle?: 'ordered' | 'shuffle' | 'block';
}
export interface ComposeResult {
  ok: boolean;
  count: number;
  channels: { number: number; name: string; items: number }[];
  skipped: { name: string; reason: string }[];
}
export interface PromptOptions {
  target?: string;
  preferences?: string;
  start?: number;
  include_genres?: string[];
  exclude_genres?: string[];
  include_decades?: string[];
  exclude_decades?: string[];
  include_types?: string[];
  exclude_types?: string[];
}
export interface PlexLibrary { key: string; title: string; type: 'movie' | 'show' }
export interface PlexCollection { id: string; name: string; count: number; section: string; summary: string; has_poster: boolean }
export interface CollectionSelection { name: string; channel_number: number; include: boolean }
export interface LogEntry { name: string; size: number; modified: number }

// ── SSE streaming ──────────────────────────────────────────────────────────────

export type StreamEvent =
  | { type: 'start'; cmd: string; log: string }
  | { type: 'line'; text: string }
  | { type: 'done'; returncode: number; log: string };

export async function streamPipeline(
  endpoint: string,
  params: Record<string, string> = {},
  onEvent: (e: StreamEvent) => void,
  body?: unknown,
): Promise<number> {
  const qs = new URLSearchParams(params).toString();
  const url = `${BASE}${endpoint}${qs ? `?${qs}` : ''}`;
  const fetchOpts: RequestInit = { method: 'POST' };
  if (body !== undefined) {
    fetchOpts.body = JSON.stringify(body);
    fetchOpts.headers = { 'Content-Type': 'application/json' };
  }
  const res = await fetch(url, fetchOpts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  if (!res.body) throw new Error('No body');

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  let code = -1;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop() ?? '';
    for (const part of parts) {
      const line = part.startsWith('data: ') ? part.slice(6) : part;
      if (!line.trim()) continue;
      try {
        const ev = JSON.parse(line) as StreamEvent;
        onEvent(ev);
        if (ev.type === 'done') code = ev.returncode;
      } catch { /* ignore parse errors */ }
    }
  }
  return code;
}
