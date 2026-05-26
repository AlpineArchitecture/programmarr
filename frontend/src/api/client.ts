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
  getPrompt: (target?: string, prefs?: string) => {
    const p = new URLSearchParams();
    if (target) p.set('target', target);
    if (prefs) p.set('preferences', prefs);
    return req<{ content: string }>(`/pipeline/prompt?${p}`);
  },
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
};

// ── Types ──────────────────────────────────────────────────────────────────────

export interface ConnStatus { ok: boolean; url: string; error?: string }
export interface TunarrChannel { number: number; name: string; id?: string }
export interface Channel {
  number: number;
  name: string;
  shuffle: 'ordered' | 'shuffle' | 'block';
  content: (string | { collection: string })[];
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
