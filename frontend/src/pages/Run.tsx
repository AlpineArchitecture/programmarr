import {
  Alert, Badge, Box, Button, Card, Center, Checkbox, Chip, Code, Collapse, Divider, Group,
  Image, Loader, NumberInput, ScrollArea, SimpleGrid, Stack,
  Stepper, Text, Textarea, ThemeIcon, Title, Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Dropzone } from '@mantine/dropzone';
import {
  IconAlertCircle, IconArrowRight, IconCheck, IconChevronDown, IconCopy, IconDownload,
  IconExternalLink, IconPlayerPlay, IconRobot, IconSparkles, IconStack2,
  IconUpload, IconWand, IconX,
} from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import {
  api, streamPipeline, StreamEvent, PlexCollection, PlexLibrary, CollectionSelection,
  LibraryFacets, GenreFacet, DecadeFacet, PromptOptions,
} from '../api/client';
import type { Channel } from '../api/client';
import TerminalOutput from '../components/TerminalOutput';

// ── Types ────────────────────────────────────────────────────────────────────────

type Method = 'ai' | 'no-ai' | 'collections';
type ContentType = 'marathons' | 'tv_blocks' | 'movies' | 'franchise' | 'specialty';

const TYPE_META: { key: ContentType; label: string; aiOnly: boolean }[] = [
  { key: 'marathons', label: 'TV Marathons', aiOnly: false },
  { key: 'tv_blocks', label: 'TV Blocks', aiOnly: true },
  { key: 'movies', label: 'Movie channels', aiOnly: false },
  { key: 'franchise', label: 'Franchise', aiOnly: true },
  { key: 'specialty', label: 'Specialty', aiOnly: true },
];

interface PlannerState {
  types: Record<ContentType, boolean>;
  genres: Record<string, boolean>;   // keyed by Plex tag
  decades: Record<string, boolean>;  // keyed by label
  canonical: GenreFacet[];
  more: GenreFacet[];
  decadeFacets: DecadeFacet[];
  target: number | string;
  theme: string;
  loaded: boolean;
}

// Setup carries the upfront decisions through the whole flow.
interface SetupState {
  method: Method;
  includeCollections: boolean;
  fetchArt: boolean;
  protectedNums: number[];
  start: number;
}

// ── Shared helpers ─────────────────────────────────────────────────────────────

function StatBox({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Stack gap={2} align="center" p="sm">
      <Text size="xl" fw={800} c="orange.4">{value}</Text>
      <Text size="xs" c="dimmed" ta="center">{label}</Text>
    </Stack>
  );
}

function ResultsCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <Card withBorder p="lg">
      <Group gap="sm" mb="lg" wrap="nowrap">
        <ThemeIcon color="green" variant="light" size="xl" radius="xl" style={{ flexShrink: 0 }}>
          <IconCheck size={20} />
        </ThemeIcon>
        <Box>
          <Text fw={700} size="lg">{title}</Text>
          {subtitle && <Text size="sm" c="dimmed">{subtitle}</Text>}
        </Box>
      </Group>
      {children}
    </Card>
  );
}

function getChannelBreakdown(channels: Channel[]) {
  return {
    marathons: channels.filter(c => c.number >= 10 && c.number <= 19).length,
    tvBlocks:  channels.filter(c => c.number >= 20 && c.number <= 29).length,
    movies:    channels.filter(c => c.number >= 30 && c.number <= 49).length,
    franchise: channels.filter(c => c.number >= 50 && c.number <= 69).length,
    specialty: channels.filter(c => c.number >= 70 && c.number <= 79).length,
    collections: channels.filter(c => c.number >= 80).length,
    totalContent: channels.reduce((s, c) => s + c.content.length, 0),
  };
}

function parseRunStats(lines: string[]) {
  const summaryLine = lines.slice().reverse().find(l => l.includes('Done:'));
  const m = summaryLine?.match(/Done:\s*(\d+) created,\s*(\d+) skipped/);
  return { created: m ? parseInt(m[1]) : null, skipped: m ? parseInt(m[2]) : null };
}

// Derive include/exclude lists from planner toggle state.
function plannerToPromptOptions(p: PlannerState, start: number): PromptOptions {
  const shown = [...p.canonical, ...p.more];
  const checkedGenres = shown.filter(g => p.genres[g.tag]).map(g => g.tag);
  // Only an unchecked *canonical* genre is a hard "never create" — "More" genres
  // left unchecked are simply not requested.
  const excludedGenres = p.canonical.filter(g => !p.genres[g.tag]).map(g => g.tag);
  const checkedDecades = p.decadeFacets.filter(d => p.decades[d.label]).map(d => d.label);
  const excludedDecades = p.decadeFacets.filter(d => !p.decades[d.label]).map(d => d.label);
  const checkedTypes = TYPE_META.filter(t => p.types[t.key]).map(t => t.key);
  const excludedTypes = TYPE_META.filter(t => !p.types[t.key]).map(t => t.key);
  return {
    target: String(p.target),
    preferences: p.theme,
    start,
    include_genres: checkedGenres,
    exclude_genres: excludedGenres,
    include_decades: checkedDecades,
    exclude_decades: excludedDecades,
    include_types: checkedTypes,
    exclude_types: excludedTypes,
  };
}

// Derive No-AI CLI params (only marathons + movies are data-driven there).
function plannerToNoAiParams(p: PlannerState, start: number): Record<string, string> {
  const shown = [...p.canonical, ...p.more];
  const genres = shown.filter(g => p.genres[g.tag]).map(g => g.tag);
  const decades = p.decadeFacets.filter(d => p.decades[d.label]).map(d => String(d.start));
  const types = TYPE_META.filter(t => !t.aiOnly && p.types[t.key]).map(t => t.key);
  const params: Record<string, string> = {};
  if (start !== 10) params.start = String(start);
  params.genres = genres.join(',');
  params.decades = decades.join(',');
  params.types = types.join(',');
  return params;
}

// ── Setup screen ───────────────────────────────────────────────────────────────

function MethodCard({ icon, title, desc, active, onClick }: {
  icon: React.ReactNode; title: string; desc: string; active: boolean; onClick: () => void;
}) {
  return (
    <Card
      withBorder p="md" onClick={onClick}
      style={{
        cursor: 'pointer',
        borderColor: active ? 'var(--mantine-color-orange-5)' : undefined,
        backgroundColor: active ? 'var(--mantine-color-dark-6)' : undefined,
      }}
    >
      <Group gap="sm" wrap="nowrap">
        <ThemeIcon color={active ? 'orange' : 'gray'} variant="light" size="lg" radius="md" style={{ flexShrink: 0 }}>
          {icon}
        </ThemeIcon>
        <Box>
          <Text fw={700} size="sm">{title}</Text>
          <Text size="xs" c="dimmed">{desc}</Text>
        </Box>
      </Group>
    </Card>
  );
}

function SetupStep({ setup, onChange, onDone }: {
  setup: SetupState;
  onChange: (patch: Partial<SetupState>) => void;
  onDone: () => void;
}) {
  const [hasTmdb, setHasTmdb] = useState(false);
  const [tunarrChannels, setTunarrChannels] = useState<{ number: number; name: string }[]>([]);
  const [checkedNums, setCheckedNums] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);

  function calcStart(checked: Set<number>): number {
    if (checked.size === 0) return 1;
    return Math.ceil((Math.max(...checked) + 1) / 10) * 10;
  }

  useEffect(() => {
    Promise.all([
      api.getConfigStatus().then(s => setHasTmdb(s.has_tmdb)).catch(() => {}),
      api.getTunarrChannels().then(chs => {
        const sorted = [...chs].sort((a, b) => a.number - b.number);
        setTunarrChannels(sorted);
        const all = new Set(sorted.map(c => c.number));
        setCheckedNums(all);
        onChange({ protectedNums: [...all], start: calcStart(all) });
      }).catch(() => {}),
    ]).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // If no TMDB key, art can't be on.
  useEffect(() => {
    if (!hasTmdb && setup.fetchArt) onChange({ fetchArt: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasTmdb]);

  function toggleChannel(num: number, checked: boolean) {
    const next = new Set(checkedNums);
    if (checked) next.add(num); else next.delete(num);
    setCheckedNums(next);
    onChange({ protectedNums: [...next], start: calcStart(next) });
  }

  function setAll(on: boolean) {
    const next = on ? new Set(tunarrChannels.map(c => c.number)) : new Set<number>();
    setCheckedNums(next);
    onChange({ protectedNums: [...next], start: calcStart(next) });
  }

  const checkedCount = checkedNums.size;

  return (
    <Stack gap="lg">
      {/* Method */}
      <Card withBorder p="md">
        <Text fw={700} mb="sm">How should we build your channels?</Text>
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
          <MethodCard
            icon={<IconSparkles size={18} />} title="Let AI design them"
            desc="An LLM curates themed channels from your library. Most creative."
            active={setup.method === 'ai'} onClick={() => onChange({ method: 'ai' })}
          />
          <MethodCard
            icon={<IconWand size={18} />} title="Auto-generate"
            desc="Build genre, decade & marathon channels automatically. No AI needed."
            active={setup.method === 'no-ai'} onClick={() => onChange({ method: 'no-ai' })}
          />
          <MethodCard
            icon={<IconStack2 size={18} />} title="Just my collections"
            desc="One channel per Plex collection. Skips the library scan."
            active={setup.method === 'collections'} onClick={() => onChange({ method: 'collections' })}
          />
        </SimpleGrid>
      </Card>

      {/* Options */}
      <Card withBorder p="md">
        <Text fw={700} mb="sm">Options</Text>
        <Stack gap="sm">
          {setup.method !== 'collections' && (
            <Checkbox
              label="Also add channels from my Plex collections"
              description="You'll choose which ones before deploying."
              checked={setup.includeCollections}
              onChange={(e) => onChange({ includeCollections: e.currentTarget.checked })}
            />
          )}
          <Tooltip
            label="Add a TMDB API key in Settings to enable channel art"
            disabled={hasTmdb} withArrow
          >
            <Checkbox
              label="Fetch channel art from TMDB"
              description="Downloads real show/movie logos for solo-title channels after deploy."
              checked={setup.fetchArt}
              disabled={!hasTmdb}
              onChange={(e) => onChange({ fetchArt: e.currentTarget.checked })}
            />
          </Tooltip>
        </Stack>
      </Card>

      {/* Existing lineup keep/wipe */}
      <Card withBorder p="md">
        <Group justify="space-between" mb="sm">
          <Text fw={700}>Existing Tunarr channels</Text>
          {tunarrChannels.length > 0 && (
            <Group gap={4}>
              <Button size="xs" variant="subtle" py={2} onClick={() => setAll(true)}>Keep all</Button>
              <Button size="xs" variant="subtle" py={2} onClick={() => setAll(false)}>Wipe all</Button>
            </Group>
          )}
        </Group>
        {loading ? (
          <Group gap="sm"><Loader size="xs" color="orange" /><Text size="sm" c="dimmed">Checking Tunarr…</Text></Group>
        ) : tunarrChannels.length === 0 ? (
          <Text size="sm" c="dimmed">No channels in Tunarr yet — starting fresh.</Text>
        ) : (
          <>
            <ScrollArea h={170} style={{ borderRadius: 4, border: '1px solid var(--mantine-color-dark-5)' }}>
              <Stack gap={0}>
                {tunarrChannels.map(c => (
                  <Group key={c.number} gap="xs" px="sm" py={5}
                    style={{ borderBottom: '1px solid var(--mantine-color-dark-6)', opacity: checkedNums.has(c.number) ? 1 : 0.4 }}>
                    <Checkbox size="xs" checked={checkedNums.has(c.number)}
                      onChange={(e) => toggleChannel(c.number, e.currentTarget.checked)} style={{ flexShrink: 0 }} />
                    <Text size="xs" c="dimmed" w={36} style={{ flexShrink: 0 }}>#{c.number}</Text>
                    <Text size="xs" lineClamp={1}>{c.name}</Text>
                  </Group>
                ))}
              </Stack>
            </ScrollArea>
            <Text size="xs" c={checkedCount < tunarrChannels.length ? 'yellow.5' : 'dimmed'} mt="xs">
              {checkedCount === tunarrChannels.length
                ? `All ${checkedCount} kept. New channels start at #${setup.start}.`
                : checkedCount === 0
                  ? 'All existing channels will be wiped and rebuilt.'
                  : `${checkedCount} kept, ${tunarrChannels.length - checkedCount} wiped. New channels start at #${setup.start}.`}
            </Text>
          </>
        )}
      </Card>

      <Group>
        <Button color="orange" rightSection={<IconArrowRight size={15} />} onClick={onDone}>
          {setup.method === 'collections' ? 'Continue to Collections' : 'Continue to Export'}
        </Button>
      </Group>
    </Stack>
  );
}

// ── Export step ──────────────────────────────────────────────────────────────────

function ExportStep({ onDone }: { onDone: () => void }) {
  const [libraries, setLibraries] = useState<PlexLibrary[]>([]);
  const [libSels, setLibSels] = useState<Record<string, boolean>>({});
  const [libLoading, setLibLoading] = useState(true);
  const [libError, setLibError] = useState<string | null>(null);

  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [success, setSuccess] = useState(false);
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof api.getCsvInfo>> | null>(null);
  const [noCrossref, setNoCrossref] = useState(false);

  useEffect(() => {
    api.getLibraries()
      .then(libs => { setLibraries(libs); setLibSels(Object.fromEntries(libs.map(l => [l.key, true]))); })
      .catch(err => setLibError(err.message))
      .finally(() => setLibLoading(false));
  }, []);

  const movieLibs = libraries.filter(l => l.type === 'movie');
  const tvLibs = libraries.filter(l => l.type === 'show');
  const selectedCount = Object.values(libSels).filter(Boolean).length;

  async function run() {
    const movieSections = movieLibs.filter(l => libSels[l.key]).map(l => l.key);
    const tvSections = tvLibs.filter(l => libSels[l.key]).map(l => l.key);
    setLines([]); setDone(false); setSummary(null); setRunning(true);
    try {
      const code = await streamPipeline('/pipeline/export', {}, (ev: StreamEvent) => {
        if (ev.type === 'line') setLines(l => [...l, ev.text]);
      }, { no_crossref: noCrossref, movie_sections: movieSections, tv_sections: tvSections });
      const ok = code === 0;
      setSuccess(ok); setDone(true);
      if (ok) setSummary(await api.getCsvInfo());
    } catch (e: any) {
      setLines(l => [...l, `Error: ${e.message}`]); setDone(true); setSuccess(false);
    } finally { setRunning(false); }
  }

  const skipped = (summary?.skipped_movies ?? 0) + (summary?.skipped_shows ?? 0);

  return (
    <Stack gap="md">
      <Card withBorder p="md">
        <Text fw={700} mb="sm">Libraries to scan</Text>
        {libLoading && <Group gap="sm"><Loader size="xs" color="orange" /><Text size="sm" c="dimmed">Fetching Plex libraries…</Text></Group>}
        {!libLoading && libError && (
          <Alert color="yellow" variant="light" icon={<IconAlertCircle size={16} />}>
            Could not load libraries — export will auto-detect: {libError}
          </Alert>
        )}
        {!libLoading && !libError && libraries.length > 0 && (
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
            {movieLibs.length > 0 && (
              <Stack gap={6}>
                <Text size="xs" fw={600} c="dimmed" tt="uppercase">Movies</Text>
                {movieLibs.map(lib => (
                  <Checkbox key={lib.key} label={lib.title} checked={libSels[lib.key] ?? true}
                    onChange={(e) => { const v = e.currentTarget.checked; setLibSels(s => ({ ...s, [lib.key]: v })); }}
                    size="sm" disabled={running} />
                ))}
              </Stack>
            )}
            {tvLibs.length > 0 && (
              <Stack gap={6}>
                <Text size="xs" fw={600} c="dimmed" tt="uppercase">TV Shows</Text>
                {tvLibs.map(lib => (
                  <Checkbox key={lib.key} label={lib.title} checked={libSels[lib.key] ?? true}
                    onChange={(e) => { const v = e.currentTarget.checked; setLibSels(s => ({ ...s, [lib.key]: v })); }}
                    size="sm" disabled={running} />
                ))}
              </Stack>
            )}
          </SimpleGrid>
        )}
      </Card>

      <Group align="center">
        <Button leftSection={<IconPlayerPlay size={15} />} color="orange" onClick={run} loading={running}
          disabled={!libLoading && !libError && selectedCount === 0}>
          {running ? 'Exporting…' : done ? 'Re-run Export' : 'Run Export'}
        </Button>
        {done && !success && <Button variant="subtle" color="red" onClick={run}>Retry</Button>}
        <Checkbox label="Skip Tunarr cross-reference" checked={noCrossref}
          onChange={(e) => setNoCrossref(e.currentTarget.checked)} disabled={running} size="sm" />
      </Group>

      {done && success && summary && (
        <Card withBorder p="sm" bg="dark.8">
          <Group justify="space-between" wrap="nowrap" gap="sm">
            <Group gap="sm" wrap="nowrap">
              <ThemeIcon color="green" variant="light" size="sm" radius="xl" style={{ flexShrink: 0 }}><IconCheck size={12} /></ThemeIcon>
              <Text size="sm" fw={600}>
                {summary.movies ?? '—'} movies · {summary.tv_shows ?? '—'} TV shows · {Math.round((summary.size ?? 0) / 1024)} KB
                {skipped > 0 && <Text span size="sm" c="yellow.4"> · {skipped} skipped (not in Tunarr)</Text>}
              </Text>
            </Group>
            <Button size="xs" color="orange" rightSection={<IconArrowRight size={12} />} onClick={onDone} style={{ flexShrink: 0 }}>Continue</Button>
          </Group>
        </Card>
      )}

      {(running || done) && <TerminalOutput lines={lines} done={done} success={success} />}
    </Stack>
  );
}

// ── Planner step (toggles) ───────────────────────────────────────────────────────

function PlannerStep({ method, planner, setPlanner, start, onNext, onGenerate }: {
  method: Method;
  planner: PlannerState;
  setPlanner: (p: PlannerState) => void;
  start: number;
  onNext: () => void;          // AI: go to prompt
  onGenerate: () => void;      // No-AI: generate then advance
}) {
  const [loading, setLoading] = useState(!planner.loaded);
  const [error, setError] = useState<string | null>(null);
  const [showMore, setShowMore] = useState(false);

  useEffect(() => {
    if (planner.loaded) { setLoading(false); return; }
    api.getFacets()
      .then((f: LibraryFacets) => {
        if (!f.exists) { setError('Run Export first.'); return; }
        const canonical = f.genres?.canonical ?? [];
        const more = f.genres?.more ?? [];
        const decadeFacets = f.decades ?? [];
        const minItems = f.min_items ?? 5;
        // Default-on: canonical genres with enough items, all present decades, all types.
        const genres: Record<string, boolean> = {};
        canonical.forEach(g => { genres[g.tag] = g.count >= minItems; });
        more.forEach(g => { genres[g.tag] = false; });
        const decades: Record<string, boolean> = {};
        decadeFacets.forEach(d => { decades[d.label] = true; });
        const types = { marathons: true, tv_blocks: true, movies: true, franchise: true, specialty: true };
        setPlanner({ ...planner, canonical, more, decadeFacets, genres, decades, types, loaded: true });
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function patch(p: Partial<PlannerState>) { setPlanner({ ...planner, ...p }); }
  function setType(k: ContentType, v: boolean) { patch({ types: { ...planner.types, [k]: v } }); }
  function setGenre(tag: string, v: boolean) { patch({ genres: { ...planner.genres, [tag]: v } }); }
  function setDecade(label: string, v: boolean) { patch({ decades: { ...planner.decades, [label]: v } }); }

  const moviesOn = planner.types.movies;

  if (loading) {
    return <Center py="xl"><Stack align="center" gap="sm"><Loader color="orange" /><Text size="sm" c="dimmed">Reading your library…</Text></Stack></Center>;
  }
  if (error) {
    return <Alert color="yellow" variant="light" icon={<IconAlertCircle size={16} />}>{error}</Alert>;
  }

  function GenreChip({ g }: { g: GenreFacet }) {
    return (
      <Chip size="sm" checked={!!planner.genres[g.tag]} disabled={!moviesOn}
        onChange={(v) => setGenre(g.tag, v)} color="orange" variant="outline">
        {g.display} <Text span c="dimmed" size="xs">({g.count})</Text>
      </Chip>
    );
  }

  return (
    <Stack gap="lg">
      <Text size="sm" c="dimmed">
        Pick what kinds of channels to {method === 'ai' ? 'ask for' : 'build'}. {method === 'ai'
          ? 'Checked items are must-haves; unchecked genres are off-limits. The AI can still surprise you with extra finds.'
          : 'Only the checked blocks get generated.'}
      </Text>

      {/* Content types */}
      <Card withBorder p="md">
        <Text fw={700} mb="xs">Content types</Text>
        <Group gap="sm">
          {TYPE_META.map(t => {
            const disabled = method === 'no-ai' && t.aiOnly;
            const chip = (
              <Chip size="sm" checked={!!planner.types[t.key] && !disabled} disabled={disabled}
                onChange={(v) => setType(t.key, v)} color="orange" variant="outline">
                {t.label}
              </Chip>
            );
            return disabled
              ? <Tooltip key={t.key} label="Requires AI — Auto-generate only does Marathons + Movies" withArrow>{chip}</Tooltip>
              : <Box key={t.key}>{chip}</Box>;
          })}
        </Group>
      </Card>

      {/* Genres */}
      <Card withBorder p="md" style={{ opacity: moviesOn ? 1 : 0.5 }}>
        <Text fw={700} mb={2}>Movie genres</Text>
        <Text size="xs" c="dimmed" mb="sm">{moviesOn ? 'From your library, with item counts.' : 'Enable “Movie channels” above to choose genres.'}</Text>
        <Group gap="xs">
          {planner.canonical.map(g => <GenreChip key={g.tag} g={g} />)}
        </Group>
        {planner.more.length > 0 && (
          <>
            <Button variant="subtle" size="xs" color="gray" mt="sm" px={4}
              rightSection={<IconChevronDown size={13} style={{ transform: showMore ? 'rotate(180deg)' : undefined, transition: 'transform .15s' }} />}
              onClick={() => setShowMore(v => !v)} disabled={!moviesOn}>
              More genres ({planner.more.length})
            </Button>
            <Collapse in={showMore}>
              <Group gap="xs" mt="xs">
                {planner.more.map(g => <GenreChip key={g.tag} g={g} />)}
              </Group>
            </Collapse>
          </>
        )}
      </Card>

      {/* Decades */}
      <Card withBorder p="md" style={{ opacity: moviesOn ? 1 : 0.5 }}>
        <Text fw={700} mb="sm">Decades</Text>
        {planner.decadeFacets.length === 0 ? (
          <Text size="xs" c="dimmed">No dated movies found.</Text>
        ) : (
          <Group gap="xs">
            {planner.decadeFacets.map(d => (
              <Chip key={d.label} size="sm" checked={!!planner.decades[d.label]} disabled={!moviesOn}
                onChange={(v) => setDecade(d.label, v)} color="orange" variant="outline">
                {d.label} <Text span c="dimmed" size="xs">({d.count})</Text>
              </Chip>
            ))}
          </Group>
        )}
      </Card>

      {/* AI-only: target + theme */}
      {method === 'ai' && (
        <Card withBorder p="md">
          <Text fw={700} mb="sm">Fine-tuning</Text>
          <Group align="flex-end" gap="md" mb="sm">
            <NumberInput label="Target channel count" w={120} value={planner.target}
              onChange={(v) => patch({ target: v })} min={1} max={500} step={1} size="sm" />
            <Text size="sm" c="dimmed" mb={6}>roughly 1 channel per 15–20 titles</Text>
          </Group>
          <Textarea label="Anything specific you want? (optional)"
            placeholder="e.g. a Batman channel, 90s cartoons, classic westerns, a Studio Ghibli block…"
            value={planner.theme} onChange={(e) => patch({ theme: e.currentTarget.value })}
            minRows={2} autosize maxRows={6} size="sm" maxLength={500} />
        </Card>
      )}

      <Group>
        {method === 'ai' ? (
          <Button color="orange" rightSection={<IconArrowRight size={15} />} onClick={onNext}>Get the AI prompt</Button>
        ) : (
          <Button color="orange" leftSection={<IconWand size={15} />} onClick={onGenerate}>Generate Channels</Button>
        )}
        <Text size="xs" c="dimmed">Channels will start at #{start}.</Text>
      </Group>
    </Stack>
  );
}

// ── No-AI generation runner (invoked from Planner's Generate button) ──────────────

function NoAiRunStep({ planner, start, onDone }: { planner: PlannerState; start: number; onDone: () => void }) {
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [success, setSuccess] = useState(false);
  const [count, setCount] = useState<number | null>(null);

  async function run() {
    setLines([]); setDone(false); setCount(null); setRunning(true);
    try {
      const code = await streamPipeline('/pipeline/no-ai', plannerToNoAiParams(planner, start), (ev) => {
        if (ev.type === 'line') setLines(l => [...l, ev.text]);
      });
      const ok = code === 0; setSuccess(ok); setDone(true);
      if (ok) { try { setCount((await api.getChannels()).channels.length); } catch { /* ignore */ } }
    } catch (e: any) {
      setLines(l => [...l, `Error: ${e.message}`]); setDone(true); setSuccess(false);
    } finally { setRunning(false); }
  }

  useEffect(() => { run(); /* auto-run on entry */ // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">Building channels from your library and toggle selections…</Text>
      {(running || done) && <TerminalOutput lines={lines} done={done} success={success} />}
      {done && !success && <Button variant="subtle" color="red" onClick={run}>Retry</Button>}
      {done && success && count !== null && (
        <ResultsCard title={`${count} channels generated`} subtitle="channels.json is ready">
          <Button color="orange" rightSection={<IconArrowRight size={15} />} onClick={onDone}>Continue</Button>
        </ResultsCard>
      )}
    </Stack>
  );
}

// ── AI Prompt walkthrough ─────────────────────────────────────────────────────────

function PromptStep({ planner, start, onValidated }: {
  planner: PlannerState;
  start: number;
  onValidated: (channels: Channel[]) => void;
}) {
  const [prompt, setPrompt] = useState('');
  const [csvInfo, setCsvInfo] = useState<any>(null);
  const [pasteText, setPasteText] = useState('');
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; count?: number; error?: string; channels?: Channel[] } | null>(null);

  useEffect(() => {
    api.getCsvInfo().then(setCsvInfo).catch(() => {});
    api.buildPrompt(plannerToPromptOptions(planner, start)).then(p => setPrompt(p.content)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function copyPrompt() {
    await navigator.clipboard.writeText(prompt);
    notifications.show({ message: 'Prompt copied', color: 'green', icon: <IconCheck size={14} /> });
  }
  async function validatePaste() {
    if (!pasteText.trim()) return;
    setValidating(true); setResult(await api.validateText(pasteText)); setValidating(false);
  }
  async function handleFileDrop(files: File[]) {
    setValidating(true); setResult(await api.validateFile(files[0])); setValidating(false);
  }

  const breakdown = result?.ok && result.channels ? getChannelBreakdown(result.channels) : null;

  function Step({ n, children }: { n: number; children: React.ReactNode }) {
    return (
      <Group gap="sm" wrap="nowrap" align="flex-start">
        <ThemeIcon color="orange" variant="light" radius="xl" size="md" style={{ flexShrink: 0 }}>
          <Text size="xs" fw={700}>{n}</Text>
        </ThemeIcon>
        <Box style={{ flex: 1, minWidth: 0 }}>{children}</Box>
      </Group>
    );
  }

  return (
    <Stack gap="lg">
      <Alert color="blue" variant="light" icon={<IconRobot size={16} />}>
        You'll hand this prompt to any AI chat, give it your library file, and paste its answer back here.
        Use the most capable model you have access to (Claude Opus, Gemini Pro, GPT-4-class) — small/fast models often cut the list short.
      </Alert>

      <Card withBorder p="lg">
        <Stack gap="lg">
          <Step n={1}>
            <Group justify="space-between" wrap="nowrap">
              <Text size="sm" fw={600}>Copy the prompt</Text>
              <Button size="xs" variant="light" color="orange" leftSection={<IconCopy size={13} />} onClick={copyPrompt} disabled={!prompt}>Copy</Button>
            </Group>
            <ScrollArea h={180} mt="xs" style={{ backgroundColor: '#0d0e0f', borderRadius: 4, border: '1px solid var(--mantine-color-dark-4)' }}>
              <Box p="sm"><Text size="xs" style={{ fontFamily: 'ui-monospace, monospace', whiteSpace: 'pre-wrap', color: '#d4d4d4' }}>{prompt || 'Building prompt…'}</Text></Box>
            </ScrollArea>
          </Step>

          <Step n={2}>
            <Text size="sm" fw={600} mb={4}>Open your AI chat</Text>
            <Group gap="xs">
              <Button component="a" href="https://chatgpt.com" target="_blank" rel="noreferrer" size="xs" variant="default" rightSection={<IconExternalLink size={12} />}>ChatGPT</Button>
              <Button component="a" href="https://claude.ai" target="_blank" rel="noreferrer" size="xs" variant="default" rightSection={<IconExternalLink size={12} />}>Claude</Button>
              <Button component="a" href="https://gemini.google.com" target="_blank" rel="noreferrer" size="xs" variant="default" rightSection={<IconExternalLink size={12} />}>Gemini</Button>
            </Group>
          </Step>

          <Step n={3}>
            <Text size="sm" fw={600} mb={4}>Paste the prompt, then attach your library file</Text>
            <Text size="xs" c="dimmed" mb="xs">
              Most chats let you attach a file — use that for best results. If yours can't, paste the CSV's contents right after the prompt instead.
            </Text>
            {csvInfo?.exists ? (
              <Button component="a" href="/api/pipeline/csv" download="plex_library.csv" leftSection={<IconDownload size={14} />} color="orange" variant="light" size="xs">
                Download plex_library.csv ({csvInfo.rows?.toLocaleString()} titles)
              </Button>
            ) : (
              <Alert color="yellow" variant="light" icon={<IconAlertCircle size={14} />}>Run Export first to generate the library file.</Alert>
            )}
          </Step>

          <Step n={4}>
            <Text size="sm" fw={600}>Copy the AI's channel list — the JSON only</Text>
            <Text size="xs" c="dimmed">
              Copy just the channel lines (each looks like <Code>{'{"number": 30, "name": …}'}</Code>, one per line).
              Leave out any intro, explanation, or closing remarks the AI writes around the list — paste only the JSON.
            </Text>
          </Step>

          <Step n={5}>
            <Text size="sm" fw={600} mb="xs">Paste the channel list back here</Text>
            {!result?.ok ? (
              <Stack gap="sm">
                <Textarea placeholder="Paste only the JSON channel lines here…" minRows={5} autosize maxRows={12}
                  value={pasteText} onChange={(e) => { setPasteText(e.currentTarget.value); setResult(null); }}
                  styles={{ input: { fontFamily: 'ui-monospace, monospace', fontSize: 12 } }} />
                <Text size="xs" c="dimmed" ta="center">— or —</Text>
                <Dropzone onDrop={handleFileDrop} accept={{ 'application/json': ['.json'], 'text/plain': ['.jsonl', '.txt'] }}
                  maxFiles={1} loading={validating} styles={{ root: { borderColor: 'var(--mantine-color-dark-4)' } }}>
                  <Group justify="center" gap="sm" py="sm"><IconUpload size={18} color="var(--mantine-color-dimmed)" /><Text size="sm" c="dimmed">Drop the saved .json / .jsonl file here</Text></Group>
                </Dropzone>
                {result && !result.ok && <Alert color="red" icon={<IconX size={16} />} variant="light">Invalid — {result.error}</Alert>}
                {pasteText && !result && <Button color="orange" onClick={validatePaste} loading={validating} style={{ alignSelf: 'flex-start' }}>Validate &amp; Save</Button>}
              </Stack>
            ) : (
              <Text size="xs" c="green.4">✓ Saved.</Text>
            )}
          </Step>
        </Stack>
      </Card>

      {result?.ok && breakdown && result.channels && (
        <ResultsCard title={`${result.count} channels loaded`} subtitle={`${breakdown.totalContent} content items · saved to channels.json`}>
          <SimpleGrid cols={{ base: 2, sm: 3 }} mb="md">
            {breakdown.marathons > 0 && <StatBox label="TV Marathons" value={breakdown.marathons} />}
            {breakdown.tvBlocks > 0 && <StatBox label="TV Blocks" value={breakdown.tvBlocks} />}
            {breakdown.movies > 0 && <StatBox label="Movies" value={breakdown.movies} />}
            {breakdown.franchise > 0 && <StatBox label="Franchise" value={breakdown.franchise} />}
            {breakdown.specialty > 0 && <StatBox label="Specialty" value={breakdown.specialty} />}
            {breakdown.collections > 0 && <StatBox label="Collections" value={breakdown.collections} />}
          </SimpleGrid>
          <Divider mb="md" />
          <Group>
            <Button color="orange" rightSection={<IconArrowRight size={15} />} onClick={() => onValidated(result.channels!)}>Continue</Button>
            <Button variant="subtle" size="xs" color="dimmed" onClick={() => setResult(null)}>Replace</Button>
          </Group>
        </ResultsCard>
      )}
    </Stack>
  );
}

// ── Collections step ───────────────────────────────────────────────────────────

type CollectionSel = { id: string; name: string; channel_number: number; include: boolean };

function CollectionsStep({ start, onDone }: { start: number; onDone: () => void }) {
  const [collections, setCollections] = useState<PlexCollection[]>([]);
  const [selections, setSelections] = useState<CollectionSel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const base = Math.max(80, Math.ceil(start / 10) * 10);

  useEffect(() => {
    api.getCollections()
      .then(cols => {
        setCollections(cols);
        setSelections(cols.map((c, i) => ({ id: c.id, name: c.name, channel_number: base + i, include: true })));
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updateSel(idx: number, patch: Partial<CollectionSel>) {
    setSelections(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s));
  }

  async function apply() {
    setApplying(true);
    try {
      const payload: CollectionSelection[] = selections.map(s => ({ name: s.name, channel_number: s.channel_number, include: s.include }));
      const r = await api.applyCollections(payload);
      notifications.show({ message: `${r.added} collection${r.added !== 1 ? 's' : ''} added`, color: 'green', icon: <IconCheck size={14} /> });
      onDone();
    } catch (e: any) { setError(e.message); } finally { setApplying(false); }
  }

  if (loading) return <Center py="xl"><Stack align="center" gap="sm"><Loader color="orange" /><Text size="sm" c="dimmed">Fetching collections…</Text></Stack></Center>;
  if (error) return <Alert color="red" icon={<IconX size={16} />} variant="light">{error}<Button variant="subtle" size="xs" mt="xs" onClick={onDone}>Skip Collections</Button></Alert>;
  if (collections.length === 0) return (
    <Stack gap="md">
      <Alert color="yellow" icon={<IconAlertCircle size={16} />} variant="light">No collections found in your Plex library.</Alert>
      <Button variant="subtle" color="gray" onClick={onDone}>Continue</Button>
    </Stack>
  );

  const includedCount = selections.filter(s => s.include).length;

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" c="dimmed">{collections.length} collections — select which to include.</Text>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          <Button size="xs" variant="subtle" onClick={() => setSelections(s => s.map(x => ({ ...x, include: true })))}>All</Button>
          <Button size="xs" variant="subtle" onClick={() => setSelections(s => s.map(x => ({ ...x, include: false })))}>None</Button>
          <Button size="sm" color="orange" onClick={apply} loading={applying} disabled={includedCount === 0} rightSection={<IconArrowRight size={13} />}>Add {includedCount}</Button>
          <Button variant="subtle" color="gray" size="sm" onClick={onDone}>Skip</Button>
        </Group>
      </Group>

      <Stack gap={0} style={{ border: '1px solid var(--mantine-color-dark-4)', borderRadius: 8, overflow: 'hidden' }}>
        {collections.map((col, idx) => {
          const sel = selections[idx];
          if (!sel) return null;
          return (
            <Group key={col.id} gap="sm" wrap="nowrap" px="md" py={6}
              style={{ borderBottom: idx < collections.length - 1 ? '1px solid var(--mantine-color-dark-6)' : undefined, opacity: sel.include ? 1 : 0.4 }}>
              <Checkbox checked={sel.include} onChange={(e) => updateSel(idx, { include: e.currentTarget.checked })} style={{ flexShrink: 0 }} />
              <Image src={`/api/pipeline/collections/${col.id}/poster`} w={28} h={42} radius="sm" fit="cover" style={{ flexShrink: 0 }}
                fallbackSrc="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='28' height='42'%3E%3Crect width='28' height='42' fill='%23333'/%3E%3C/svg%3E" />
              <NumberInput value={sel.channel_number}
                onChange={(v) => { const n = typeof v === 'number' ? v : parseInt(String(v)); if (!isNaN(n)) updateSel(idx, { channel_number: n }); }}
                min={1} max={999} size="xs" w={68} disabled={!sel.include} styles={{ input: { textAlign: 'center', paddingInline: 4 } }} />
              <Box style={{ flex: 1, minWidth: 0 }}>
                <Text fw={600} size="sm" lineClamp={1}>{col.name}</Text>
                <Text size="xs" c="dimmed">{col.section} · {col.count} items</Text>
              </Box>
            </Group>
          );
        })}
      </Stack>
    </Stack>
  );
}

// ── Probe parsing ────────────────────────────────────────────────────────────────

type ChannelSel = { number: number; deployNumber: number; name: string; summary: string; include: boolean };

function parseProbeChannels(lines: string[]): ChannelSel[] {
  return lines.map(line => {
    const m = line.match(/\[PROBE\] #(\d+) (.+?) \| shuffle=\w+ \| (.+)/);
    return m ? { number: parseInt(m[1]), deployNumber: parseInt(m[1]), name: m[2].trim(), summary: m[3].trim(), include: true } : null;
  }).filter(Boolean) as ChannelSel[];
}

// ── Deploy + cascade ─────────────────────────────────────────────────────────────

type CascadeStatus = 'pending' | 'running' | 'ok' | 'warn' | 'skip';

function DeployStep({ setup }: { setup: SetupState }) {
  const [probeLines, setProbeLines] = useState<string[]>([]);
  const [probeDone, setProbeDone] = useState(false);
  const [probeOk, setProbeOk] = useState(false);
  const [probing, setProbing] = useState(false);
  const [channelSels, setChannelSels] = useState<ChannelSel[]>([]);

  const [phase, setPhase] = useState<'idle' | 'deploying' | 'art' | 'sync' | 'done'>('idle');
  const [deployLines, setDeployLines] = useState<string[]>([]);
  const [deployOk, setDeployOk] = useState(false);
  const [artLines, setArtLines] = useState<string[]>([]);
  const [artStatus, setArtStatus] = useState<CascadeStatus>('pending');
  const [syncLines, setSyncLines] = useState<string[]>([]);
  const [syncStatus, setSyncStatus] = useState<CascadeStatus>('pending');
  const [showArt, setShowArt] = useState(false);
  const [showSync, setShowSync] = useState(false);

  const [config, setConfig] = useState<Record<string, string>>({});
  useEffect(() => { api.getConfig().then(setConfig).catch(() => {}); }, []);

  const protectedNums = setup.protectedNums;
  const effectiveProtected = new Set(protectedNums);
  const activeDeployNums = new Set(channelSels.filter(s => s.include).map(s => s.deployNumber));
  const conflictNums = new Set([...effectiveProtected].filter(n => activeDeployNums.has(n)));

  async function runProbe() {
    setProbeLines([]); setProbeDone(false); setChannelSels([]); setProbing(true);
    const collected: string[] = [];
    const code = await streamPipeline('/pipeline/probe', {}, (ev) => {
      if (ev.type === 'line') { collected.push(ev.text); setProbeLines([...collected]); }
    });
    const ok = code === 0;
    setProbeOk(ok); setProbeDone(true); setProbing(false);
    if (ok) setChannelSels(parseProbeChannels(collected));
  }

  useEffect(() => { runProbe(); /* auto-probe on entry */ // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updateChannelSel(idx: number, patch: Partial<ChannelSel>) {
    setChannelSels(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s));
  }

  async function runCascade() {
    // 1) Deploy
    setPhase('deploying'); setDeployLines([]);
    const body = {
      selections: channelSels.map(s => ({ original_number: s.number, deploy_number: s.deployNumber, include: s.include })),
      protected_numbers: protectedNums,
      no_delete: false,
    };
    const dcode = await streamPipeline('/pipeline/deploy-selective', {}, (ev) => { if (ev.type === 'line') setDeployLines(l => [...l, ev.text]); }, body);
    const dok = dcode === 0; setDeployOk(dok);
    if (!dok) { setPhase('done'); return; }

    // 2) Art (optional)
    if (setup.fetchArt) {
      setPhase('art'); setArtStatus('running'); setArtLines([]);
      const acode = await streamPipeline('/pipeline/images', {}, (ev) => { if (ev.type === 'line') setArtLines(l => [...l, ev.text]); });
      setArtStatus(acode === 0 ? 'ok' : 'warn');
    } else {
      setArtStatus('skip');
    }

    // 3) Sync
    setPhase('sync'); setSyncStatus('running'); setSyncLines([]);
    const scode = await streamPipeline('/pipeline/sync', {}, (ev) => { if (ev.type === 'line') setSyncLines(l => [...l, ev.text]); });
    setSyncStatus(scode === 0 ? 'ok' : 'warn');

    setPhase('done');
  }

  const deployStats = parseRunStats(deployLines);
  const includedCount = channelSels.filter(s => s.include).length;
  const tunarrUrl = config.tunarr_url || '';
  const plexLiveTvUrl = config.plex_url ? `${config.plex_url.replace(/\/$/, '')}/web/index.html#!/settings/livetv` : '';
  const xmltvUrl = tunarrUrl ? `${tunarrUrl.replace(/\/$/, '')}/api/xmltv.xml` : '';
  const cascadeRunning = phase === 'deploying' || phase === 'art' || phase === 'sync';

  function StatusRow({ status, label, children }: { status: CascadeStatus; label: string; children?: React.ReactNode }) {
    const map: Record<CascadeStatus, { icon: React.ReactNode; color: string }> = {
      pending: { icon: <Loader size={12} />, color: 'gray' },
      running: { icon: <Loader size={12} color="orange" />, color: 'orange' },
      ok: { icon: <IconCheck size={14} />, color: 'green' },
      warn: { icon: <IconAlertCircle size={14} />, color: 'yellow' },
      skip: { icon: <IconX size={12} />, color: 'gray' },
    };
    const s = map[status];
    return (
      <Group gap="sm" wrap="nowrap">
        <ThemeIcon color={s.color} variant="light" size="sm" radius="xl" style={{ flexShrink: 0 }}>{s.icon}</ThemeIcon>
        <Text size="sm" style={{ flex: 1 }}>{label}</Text>
        {children}
      </Group>
    );
  }

  // ── Done summary ──
  if (phase === 'done') {
    const syncFailed = deployOk && syncStatus === 'warn';
    return (
      <Stack gap="lg">
        <ResultsCard
          title={deployOk ? `${deployStats.created ?? '?'} channels are live in Tunarr` : 'Deploy failed'}
          subtitle={deployOk ? 'Here’s how it went' : 'Check the output below'}
        >
          <Stack gap="sm" mb="md">
            <StatusRow status={deployOk ? 'ok' : 'warn'} label={`${deployStats.created ?? '—'} channels deployed${deployStats.skipped ? `, ${deployStats.skipped} skipped` : ''}`} />
            {deployOk && (
              <StatusRow status={artStatus} label={
                artStatus === 'skip' ? 'Channel art — skipped'
                  : artStatus === 'ok' ? 'Channel art fetched'
                  : artStatus === 'warn' ? 'Channel art — finished with warnings'
                  : 'Channel art…'
              }>
                {(artStatus === 'ok' || artStatus === 'warn') && <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setShowArt(v => !v)}>details</Button>}
              </StatusRow>
            )}
            {deployOk && syncStatus === 'ok' && <StatusRow status="ok" label="Plex sync complete — your channels are in the guide" />}
          </Stack>

          {deployOk && <Collapse in={showArt}><Box mb="md"><TerminalOutput lines={artLines} done success={artStatus === 'ok'} height={180} /></Box></Collapse>}

          {/* Prominent, can't-miss manual-step callout when Plex didn't auto-sync. */}
          {syncFailed && (
            <Alert color="yellow" variant="light" icon={<IconAlertCircle size={18} />} mb="md"
              title="One more step — add your channels to Plex">
              <Text size="sm" mb="xs">
                Your channels are live in <b>Tunarr</b>, but Plex couldn’t add them to its guide automatically.
                Until you do this once, the channels <b>won’t appear in Plex Live TV</b>:
              </Text>
              <Stack gap={2} mb="sm">
                <Text size="sm">1. Open <b>Plex → Settings → Live TV &amp; DVR</b></Text>
                <Text size="sm">2. Click <b>Set Up Plex DVR</b> and pick <b>Tunarr</b> as the device</Text>
                <Text size="sm">3. When it asks for a guide source (XMLTV), paste this URL:</Text>
              </Stack>
              {xmltvUrl && (
                <Group gap="xs" wrap="nowrap" mb="sm">
                  <Code style={{ flex: 1, overflowX: 'auto', whiteSpace: 'nowrap' }}>{xmltvUrl}</Code>
                  <Button size="compact-xs" variant="light" color="yellow" leftSection={<IconCopy size={12} />}
                    onClick={() => { navigator.clipboard.writeText(xmltvUrl); notifications.show({ message: 'XMLTV URL copied', color: 'green', icon: <IconCheck size={14} /> }); }}>
                    Copy
                  </Button>
                </Group>
              )}
              <Text size="sm" mb="xs">4. Select all channels and finish the wizard.</Text>
              <Group gap="sm">
                {plexLiveTvUrl && <Button component="a" href={plexLiveTvUrl} target="_blank" rel="noreferrer" variant="light" color="grape" size="xs" leftSection={<IconExternalLink size={13} />}>Open Plex Live TV</Button>}
                <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setShowSync(v => !v)}>{showSync ? 'Hide' : 'Show'} sync log</Button>
              </Group>
              <Collapse in={showSync}><Box mt="sm"><TerminalOutput lines={syncLines} done success={false} height={180} /></Box></Collapse>
            </Alert>
          )}

          {!deployOk && <Box mb="md"><TerminalOutput lines={deployLines} done success={false} /></Box>}

          {deployOk && tunarrUrl && (
            <Group mb="md" gap="sm">
              <Button component="a" href={tunarrUrl} target="_blank" rel="noreferrer" variant="light" color="blue" size="sm" leftSection={<IconExternalLink size={14} />}>Open Tunarr</Button>
              {!syncFailed && plexLiveTvUrl && <Button component="a" href={plexLiveTvUrl} target="_blank" rel="noreferrer" variant="light" color="grape" size="sm" leftSection={<IconExternalLink size={14} />}>Open Plex Live TV</Button>}
            </Group>
          )}
          <Group>
            {!deployOk && <Button variant="light" color="orange" onClick={() => setPhase('idle')}>Back to review</Button>}
            <Button component="a" href="/" color="green" rightSection={<IconArrowRight size={15} />}>
              {deployOk ? 'Finish — go to Dashboard' : 'Go to Dashboard'}
            </Button>
          </Group>
        </ResultsCard>
      </Stack>
    );
  }

  // ── Probe + review + deploy ──
  return (
    <Stack gap="lg">
      <Card withBorder p="lg">
        <Group justify="space-between" mb="xs">
          <Text fw={700} size="lg">Review</Text>
          {probeDone && <Button size="xs" variant="subtle" color="gray" leftSection={<IconPlayerPlay size={13} />} onClick={runProbe} loading={probing}>Re-check</Button>}
        </Group>
        <Text size="sm" c="dimmed" mb="md">
          We verified every title in your lineup exists in your library — no changes have been made yet.
          {protectedNums.length > 0 && <Text span c="blue"> {protectedNums.length} existing channel{protectedNums.length !== 1 ? 's' : ''} will be kept.</Text>}
        </Text>

        {probing && <TerminalOutput lines={probeLines} done={false} success={false} />}

        {probeDone && !probeOk && <Alert color="red" variant="light" icon={<IconX size={16} />}>Probe reported errors — review the output and fix channels.json.<Box mt="sm"><TerminalOutput lines={probeLines} done success={false} /></Box></Alert>}

        {probeDone && probeOk && channelSels.length > 0 && (
          <>
            <Group justify="space-between" mb="xs">
              <Text size="sm" fw={600}>{channelSels.length} channels to deploy</Text>
              <Group gap={4}>
                <Button size="xs" variant="subtle" py={2} onClick={() => setChannelSels(s => s.map(x => ({ ...x, include: true })))}>All</Button>
                <Button size="xs" variant="subtle" py={2} onClick={() => setChannelSels(s => s.map(x => ({ ...x, include: false })))}>None</Button>
              </Group>
            </Group>
            <ScrollArea.Autosize mah={320} style={{ border: '1px solid var(--mantine-color-dark-5)', borderRadius: 4 }}>
              <Stack gap={0}>
                {channelSels.map((sel, idx) => {
                  const hasConflict = sel.include && effectiveProtected.has(sel.deployNumber);
                  return (
                    <Group key={sel.number} gap="xs" wrap="nowrap" py={5} px={6}
                      style={{ borderBottom: '1px solid var(--mantine-color-dark-6)', opacity: sel.include ? 1 : 0.4, backgroundColor: hasConflict ? 'var(--mantine-color-red-9)' : undefined }}>
                      <Checkbox size="xs" checked={sel.include} onChange={(e) => updateChannelSel(idx, { include: e.currentTarget.checked })} style={{ flexShrink: 0 }} />
                      <NumberInput value={sel.deployNumber}
                        onChange={(v) => { const n = typeof v === 'number' ? v : parseInt(String(v)); if (!isNaN(n)) updateChannelSel(idx, { deployNumber: n }); }}
                        min={1} max={999} size="xs" w={58} disabled={!sel.include} styles={{ input: { textAlign: 'center', paddingInline: 4 } }} />
                      <Text size="xs" style={{ flex: 1, minWidth: 0 }} lineClamp={1}>{sel.name}</Text>
                      {hasConflict ? <Badge size="xs" color="red" style={{ flexShrink: 0 }}>conflict</Badge>
                        : <Text size="xs" c="dimmed" style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>{sel.summary}</Text>}
                    </Group>
                  );
                })}
              </Stack>
            </ScrollArea.Autosize>
          </>
        )}
      </Card>

      {probeDone && probeOk && (
        <>
          {conflictNums.size > 0 && (
            <Alert color="red" variant="light" icon={<IconAlertCircle size={16} />}>
              {conflictNums.size} number conflict{conflictNums.size !== 1 ? 's' : ''} with kept channels — renumber the highlighted rows to continue.
            </Alert>
          )}
          <Card withBorder p="lg">
            <Text size="sm" c="dimmed" mb="md">
              Deploying writes to Tunarr now.{setup.fetchArt ? ' Channel art and' : ' '} Plex sync run automatically right after.
            </Text>
            {cascadeRunning && (
              <Stack gap="xs" mb="md">
                <StatusRow status={phase === 'deploying' ? 'running' : 'ok'} label="Deploying to Tunarr" />
                {setup.fetchArt && <StatusRow status={phase === 'art' ? 'running' : phase === 'sync' ? 'ok' : 'pending'} label="Fetching channel art" />}
                <StatusRow status={phase === 'sync' ? 'running' : 'pending'} label="Syncing with Plex" />
                <TerminalOutput
                  lines={phase === 'deploying' ? deployLines : phase === 'art' ? artLines : syncLines}
                  done={false} success height={200} />
              </Stack>
            )}
            {!cascadeRunning && (
              <Button color="orange" leftSection={<IconPlayerPlay size={15} />} onClick={runCascade}
                disabled={includedCount === 0 || conflictNums.size > 0}>
                Deploy {includedCount} Channel{includedCount !== 1 ? 's' : ''}
              </Button>
            )}
          </Card>
        </>
      )}
    </Stack>
  );
}

// ── Root ───────────────────────────────────────────────────────────────────────

const blankPlanner: PlannerState = {
  types: { marathons: true, tv_blocks: true, movies: true, franchise: true, specialty: true },
  genres: {}, decades: {}, canonical: [], more: [], decadeFacets: [],
  target: 30, theme: '', loaded: false,
};

export default function Run() {
  const [step, setStep] = useState(0);
  const [setup, setSetup] = useState<SetupState>({
    method: 'ai', includeCollections: false, fetchArt: false, protectedNums: [], start: 1,
  });
  const [planner, setPlanner] = useState<PlannerState>(blankPlanner);
  // For No-AI we route the Planner's Generate into a transient run sub-view.
  const [noAiRunning, setNoAiRunning] = useState(false);

  const { method, includeCollections } = setup;

  // Build the ordered step list for this method.
  const steps: { key: string; label: string; desc: string }[] = [
    { key: 'setup', label: 'Setup', desc: 'Choose your approach' },
  ];
  if (method !== 'collections') {
    steps.push({ key: 'export', label: 'Export', desc: 'Scan your library' });
    steps.push({ key: 'planner', label: 'Planner', desc: 'Pick what to build' });
    if (method === 'ai') steps.push({ key: 'prompt', label: 'AI Prompt', desc: 'Hand off & paste back' });
  }
  if (includeCollections || method === 'collections') {
    steps.push({ key: 'collections', label: 'Collections', desc: 'Choose collections' });
  }
  steps.push({ key: 'deploy', label: 'Deploy', desc: 'Push & sync' });

  const next = () => setStep(s => Math.min(s + 1, steps.length - 1));

  function patchSetup(p: Partial<SetupState>) { setSetup(s => ({ ...s, ...p })); }

  return (
    <Stack gap="lg">
      <Title order={2}>Build Channels</Title>

      <Stepper active={step} onStepClick={(s) => { if (s < step) { setNoAiRunning(false); setStep(s); } }} color="orange" size="sm">
        {steps.map(s => (
          <Stepper.Step key={s.key} label={s.label} description={s.desc}>
            <Box mt="lg">
              {s.key === 'setup' && <SetupStep setup={setup} onChange={patchSetup} onDone={next} />}
              {s.key === 'export' && <ExportStep onDone={next} />}
              {s.key === 'planner' && (
                noAiRunning
                  ? <NoAiRunStep planner={planner} start={setup.start} onDone={() => { setNoAiRunning(false); next(); }} />
                  : <PlannerStep
                      method={method} planner={planner} setPlanner={setPlanner} start={setup.start}
                      onNext={next}
                      onGenerate={() => setNoAiRunning(true)}
                    />
              )}
              {s.key === 'prompt' && <PromptStep planner={planner} start={setup.start} onValidated={() => next()} />}
              {s.key === 'collections' && <CollectionsStep start={setup.start} onDone={next} />}
              {s.key === 'deploy' && <DeployStep setup={setup} />}
            </Box>
          </Stepper.Step>
        ))}
      </Stepper>
    </Stack>
  );
}
