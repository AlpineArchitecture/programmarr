import {
  ActionIcon, Alert, Badge, Box, Button, Card, Center, Checkbox, Chip, Code, Collapse, Divider, Group,
  Image, Loader, NumberInput, ScrollArea, Select, SimpleGrid, Stack,
  Stepper, Switch, Text, TextInput, Textarea, ThemeIcon, Title, Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Dropzone } from '@mantine/dropzone';
import {
  IconAlertCircle, IconAlertTriangle, IconArrowRight, IconCheck, IconChevronDown, IconCopy, IconDeviceTv,
  IconDownload, IconExternalLink, IconPlayerPlay, IconRefresh, IconRobot, IconSearch, IconSparkles,
  IconStack2, IconUpload, IconWand, IconX,
} from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import {
  api, streamPipeline, StreamEvent, PlexCollection, PlexLibrary, CollectionSelection,
  LibraryFacets, CandidateSpec, CandidateKind, EntityFacet, GenreDecadeFacet, BlendFacet, ValidateResult,
  FillerList, Commercials,
} from '../api/client';
import TerminalOutput from '../components/TerminalOutput';

// Copy text to the clipboard with a fallback for insecure contexts (plain HTTP on a
// non-localhost origin, where navigator.clipboard is undefined). Shows a notification
// on success or failure so the button is never silently dead.
async function copyText(text: string, label = 'Copied'): Promise<void> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (!ok) throw new Error('copy command failed');
    }
    notifications.show({ message: label, color: 'green', icon: <IconCheck size={14} /> });
  } catch {
    notifications.show({ message: 'Copy failed — select and copy manually', color: 'red' });
  }
}

// ── Types ────────────────────────────────────────────────────────────────────────

type Method = 'build' | 'collections';

// Setup carries the upfront decisions through the whole flow.
interface SetupState {
  method: Method;
  includeCollections: boolean;
  fetchArt: boolean;
  protectedNums: number[];
  start: number;
}

// Stable candidate ids for the selected-map.
const cid = {
  genre: (t: string) => `g:${t}`,
  gd: (t: string, d: number) => `gd:${t}:${d}`,
  blend: (a: string, b: string) => `b:${[a, b].sort().join('|')}`,
  studio: (v: string) => `studio:${v}`,
  director: (v: string) => `dir:${v}`,
  actor: (v: string) => `actor:${v}`,
  tv: (g: string) => `tv:${g}`,
  marathon: (t: string) => `m:${t}`,
};

interface PlannerState {
  loaded: boolean;
  facets: LibraryFacets | null;
  activeGenres: Record<string, boolean>;   // genre tag → in play
  activeDecades: Record<string, boolean>;  // decade label → in play
  selected: Record<string, CandidateSpec>; // candidate id → spec (checked)
  curate: Record<string, boolean>;         // candidate id → "let AI split by tone"
}

// ── Shared helpers ─────────────────────────────────────────────────────────────

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

function parseRunStats(lines: string[]) {
  const summaryLine = lines.slice().reverse().find(l => l.includes('Done:'));
  const m = summaryLine?.match(/Done:\s*(\d+) created,\s*(\d+) skipped/);
  return { created: m ? parseInt(m[1]) : null, skipped: m ? parseInt(m[2]) : null };
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
        <Text fw={700} mb="sm">What do you want to do?</Text>
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
          <MethodCard
            icon={<IconWand size={18} />} title="Build a lineup"
            desc="Compose curated channels from your library — genres, decades, blends, studios, directors, actors."
            active={setup.method === 'build'} onClick={() => onChange({ method: 'build' })}
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
        <Text fw={700} mb={4}>Libraries to scan</Text>
        <Text size="xs" c="dimmed" mb="xs">Pick the libraries holding your movies &amp; shows.</Text>
        <Alert color="yellow" variant="light" icon={<IconAlertTriangle size={16} />} py="xs" mb="sm">
          <Text size="xs">
            <b>Uncheck any commercials, trailers, or bumper libraries.</b> Plex files them as “movies,”
            so they’ll sneak into your channels if left checked — those belong in Tunarr as a filler
            list (the <b>📺 Add commercials</b> toggle, next step).
          </Text>
        </Alert>
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

// ── Planner v2 — ingredients → curated candidates ────────────────────────────────

function CandRow({ id, label, count, checked, onToggle, curatable, curate, onCurate }: {
  id: string; label: string; count: number; checked: boolean; onToggle: () => void;
  curatable?: boolean; curate?: boolean; onCurate?: () => void;
}) {
  return (
    <Group key={id} gap="xs" wrap="nowrap" py={3} px={6}
      style={{ borderRadius: 4, cursor: 'pointer', backgroundColor: curate ? 'var(--mantine-color-grape-9)' : checked ? 'var(--mantine-color-dark-6)' : undefined }}
      onClick={onToggle}>
      <Checkbox size="xs" checked={checked} readOnly style={{ flexShrink: 0 }} />
      <Text size="xs" style={{ flex: 1, minWidth: 0 }} lineClamp={1}>
        {label}{curate && <Text span c="grape.4" size="xs"> · AI splits by tone</Text>}
      </Text>
      {curatable && checked && onCurate && (
        <Tooltip label={curate ? "AI will split this pool by tone" : "Let AI split this pool by tone"} withArrow>
          <ActionIcon size="sm" variant={curate ? 'filled' : 'subtle'} color="grape" style={{ flexShrink: 0 }}
            onClick={(e) => { e.stopPropagation(); onCurate(); }}>
            <IconSparkles size={13} />
          </ActionIcon>
        </Tooltip>
      )}
      <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>{count}</Text>
    </Group>
  );
}

function EntitySection({ title, kind, items, makeId, makeName, isSel, onToggle, onAddMany }: {
  title: string; kind: CandidateKind; items: EntityFacet[];
  makeId: (v: string) => string; makeName: (v: string) => string;
  isSel: (id: string) => boolean;
  onToggle: (id: string, spec: CandidateSpec) => void;
  onAddMany: (items: { id: string; spec: CandidateSpec }[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const filtered = q ? items.filter(i => i.value.toLowerCase().includes(q.toLowerCase())) : items;
  const selN = items.filter(i => isSel(makeId(i.value))).length;
  const addItems: AddItem[] = items.map(i => ({ id: makeId(i.value), spec: { kind, value: i.value, name: makeName(i.value) } }));
  return (
    <Card withBorder p="sm">
      <Group justify="space-between" wrap="nowrap" style={{ cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
          <IconChevronDown size={14} style={{ transform: open ? undefined : 'rotate(-90deg)', transition: 'transform .15s', flexShrink: 0 }} />
          <Text fw={600} size="sm" lineClamp={1}>{title} <Text span c="dimmed" size="xs">({items.length})</Text></Text>
          {selN ? <Badge size="xs" color="orange" variant="light" style={{ flexShrink: 0 }}>{selN} added</Badge> : null}
        </Group>
        <BulkButtons items={addItems} onAdd={onAddMany} />
      </Group>
      <Collapse in={open}>
        <TextInput size="xs" mt="xs" placeholder={`Search ${title.toLowerCase()}…`} value={q}
          onChange={(e) => setQ(e.currentTarget.value)} leftSection={<IconSearch size={13} />} />
        <ScrollArea.Autosize mah={220} mt="xs">
          <Stack gap={0}>
            {filtered.map(i => {
              const id = makeId(i.value);
              return <CandRow key={id} id={id} count={i.count} label={makeName(i.value)} checked={isSel(id)}
                onToggle={() => onToggle(id, { kind, value: i.value, name: makeName(i.value) })} />;
            })}
            {filtered.length === 0 && <Text size="xs" c="dimmed" p="xs">No matches.</Text>}
          </Stack>
        </ScrollArea.Autosize>
      </Collapse>
    </Card>
  );
}

type AddItem = { id: string; spec: CandidateSpec };

// Collapsible candidate group with bulk "Top 10" / "Add all" buttons. Adding from a
// header collapses the group, so a handled category folds away (minimises the wall).
function BulkButtons({ items, onAdd, onAfter }: { items: AddItem[]; onAdd: (i: AddItem[]) => void; onAfter?: () => void }) {
  return (
    <Group gap={6} wrap="nowrap" style={{ flexShrink: 0 }}>
      {items.length > 10 && (
        <Button size="compact-xs" variant="subtle" color="gray"
          onClick={(e) => { e.stopPropagation(); onAdd(items.slice(0, 10)); onAfter?.(); }}>Top 10</Button>
      )}
      <Button size="compact-xs" variant="subtle" color="gray"
        onClick={(e) => { e.stopPropagation(); onAdd(items); onAfter?.(); }}>Add all</Button>
    </Group>
  );
}

function CollapsibleSection({ title, count, selectedCount, addItems, onAdd, defaultOpen, children }: {
  title: string; count: number; selectedCount?: number;
  addItems?: AddItem[]; onAdd?: (i: AddItem[]) => void; defaultOpen?: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <Card withBorder p="sm">
      <Group justify="space-between" wrap="nowrap" style={{ cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
          <IconChevronDown size={14} style={{ transform: open ? undefined : 'rotate(-90deg)', transition: 'transform .15s', flexShrink: 0 }} />
          <Text fw={600} size="sm" lineClamp={1}>{title} <Text span c="dimmed" size="xs">({count})</Text></Text>
          {selectedCount ? <Badge size="xs" color="orange" variant="light" style={{ flexShrink: 0 }}>{selectedCount} added</Badge> : null}
        </Group>
        {addItems && onAdd && <BulkButtons items={addItems} onAdd={onAdd} onAfter={() => setOpen(false)} />}
      </Group>
      <Collapse in={open}>{children}</Collapse>
    </Card>
  );
}

// Curated, recognizable sub-genres (genre∩genre) — only the meaningful ones, named
// properly. Arbitrary pairs like "Action & Comedy" are intentionally excluded.
type SubGenre = { name: string; a: string; b: string };
const SUBGENRES: SubGenre[] = [
  { name: 'Rom-Coms', a: 'Comedy', b: 'Romance' },
  { name: 'Dark Comedies', a: 'Comedy', b: 'Crime' },
  { name: 'Horror Comedies', a: 'Comedy', b: 'Horror' },
  { name: 'Dramedies', a: 'Comedy', b: 'Drama' },
  { name: 'Romantic Dramas', a: 'Romance', b: 'Drama' },
  { name: 'Crime Thrillers', a: 'Crime', b: 'Thriller' },
  { name: 'Crime Dramas', a: 'Crime', b: 'Drama' },
  { name: 'Psychological Thrillers', a: 'Thriller', b: 'Mystery' },
  { name: 'Sci-Fi Action', a: 'Science Fiction', b: 'Action' },
  { name: 'Sci-Fi Horror', a: 'Science Fiction', b: 'Horror' },
  { name: 'Fantasy Adventures', a: 'Fantasy', b: 'Adventure' },
  { name: 'War Dramas', a: 'War', b: 'Drama' },
];

function PlannerStep({ planner, setPlanner, setup, aiExtras, setAiExtras, onDone }: {
  planner: PlannerState;
  setPlanner: (p: PlannerState) => void;
  setup: SetupState;
  aiExtras: boolean;
  setAiExtras: (v: boolean) => void;
  onDone: () => void;
}) {
  const [loading, setLoading] = useState(!planner.loaded);
  const [error, setError] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [showMore, setShowMore] = useState(false);

  // Batch options applied to every channel built here (commercials + auto-update).
  const [fillerLists, setFillerLists] = useState<FillerList[]>([]);
  const [commEnabled, setCommEnabled] = useState(false);
  const [commListId, setCommListId] = useState<string | null>(null);
  const [commPad, setCommPad] = useState('5');
  const [autoUpdate, setAutoUpdate] = useState(false);

  useEffect(() => { api.getFillerLists().then(setFillerLists).catch(() => setFillerLists([])); }, []);

  useEffect(() => {
    if (planner.loaded) { setLoading(false); return; }
    api.getFacets()
      .then((f) => {
        if (!f.exists) { setError('Run Export first.'); return; }
        const minItems = f.min_items ?? 5;
        const activeGenres: Record<string, boolean> = {};
        (f.genres?.canonical ?? []).forEach(g => { activeGenres[g.tag] = g.count >= minItems; });
        const activeDecades: Record<string, boolean> = {};
        (f.decades ?? []).forEach(d => { activeDecades[d.label] = true; });
        setPlanner({ ...planner, facets: f, activeGenres, activeDecades, loaded: true });
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const f = planner.facets;
  function patch(p: Partial<PlannerState>) { setPlanner({ ...planner, ...p }); }
  function toggleGenre(tag: string) { patch({ activeGenres: { ...planner.activeGenres, [tag]: !planner.activeGenres[tag] } }); }
  function toggleDecade(label: string) { patch({ activeDecades: { ...planner.activeDecades, [label]: !planner.activeDecades[label] } }); }

  const isSel = (id: string) => id in planner.selected;
  const isCurate = (id: string) => !!planner.curate[id];
  function toggleSel(id: string, spec: CandidateSpec) {
    const next = { ...planner.selected };
    const nextCurate = { ...planner.curate };
    if (id in next) { delete next[id]; delete nextCurate[id]; } else { next[id] = spec; }
    patch({ selected: next, curate: nextCurate });
  }
  function toggleCurate(id: string) { patch({ curate: { ...planner.curate, [id]: !planner.curate[id] } }); }
  function addMany(items: { id: string; spec: CandidateSpec }[]) {
    const next = { ...planner.selected };
    items.forEach(({ id, spec }) => { next[id] = spec; });
    patch({ selected: next });
  }

  if (loading) return <Center py="xl"><Stack align="center" gap="sm"><Loader color="orange" /><Text size="sm" c="dimmed">Reading your library…</Text></Stack></Center>;
  if (error || !f) return <Alert color="yellow" variant="light" icon={<IconAlertCircle size={16} />}>{error || 'No library data.'}</Alert>;

  const activeGenreTags = new Set(Object.keys(planner.activeGenres).filter(t => planner.activeGenres[t]));
  const activeDecadeLabels = new Set(Object.keys(planner.activeDecades).filter(l => planner.activeDecades[l]));

  // Build candidate groups from active ingredients.
  const gdName = (label: string, disp: string) => `${label} ${disp}`;
  const genreDecadeByDecade: Record<string, GenreDecadeFacet[]> = {};
  (f.genre_decade ?? []).forEach(c => {
    if (activeGenreTags.has(c.genre) && activeDecadeLabels.has(c.decade_label)) {
      (genreDecadeByDecade[c.decade_label] ||= []).push(c);
    }
  });
  const broadCands = [...(f.genres?.canonical ?? []), ...(f.genres?.more ?? [])].filter(g => activeGenreTags.has(g.tag));
  const selectedCount = Object.keys(planner.selected).length;
  const countSel = (ids: string[]) => ids.filter(id => isSel(id)).length;

  // Curated sub-genres present in the library (matched against the blend pair counts).
  const blendByKey: Record<string, BlendFacet> = {};
  (f.blends ?? []).forEach(b => { blendByKey[[...b.genres].map(g => g.toLowerCase()).sort().join('|')] = b; });
  const subGenres = SUBGENRES
    .map(s => ({ s, blend: blendByKey[[s.a, s.b].map(g => g.toLowerCase()).sort().join('|')] }))
    .filter((x): x is { s: SubGenre; blend: BlendFacet } => !!x.blend);

  // AI-curate picks are NOT built deterministically — they're handed to the AI step
  // to split by tone. Only "exact" picks go to compose.
  const exactSpecs = Object.entries(planner.selected).filter(([id]) => !planner.curate[id]).map(([, spec]) => spec);
  const curateCount = Object.keys(planner.curate).filter(id => planner.curate[id] && id in planner.selected).length;

  async function build() {
    setBuilding(true);
    try {
      const commercials: Commercials | undefined = commEnabled && commListId
        ? { filler_list_id: commListId, filler_list_name: fillerLists.find(f => f.id === commListId)?.name, pad_minutes: Number(commPad) }
        : undefined;
      const r = await api.composeChannels(exactSpecs, setup.start, { live: autoUpdate, commercials });
      if (r.skipped.length) notifications.show({ message: `${r.skipped.length} candidate(s) skipped — no matching titles`, color: 'yellow' });
      const extras = [commercials && 'commercials', autoUpdate && 'auto-update'].filter(Boolean).join(' + ');
      notifications.show({ message: `${r.count} channels built${extras ? ` (${extras})` : ''}`, color: 'green', icon: <IconCheck size={14} /> });
      onDone();
    } catch (e: any) {
      notifications.show({ message: `Build failed: ${e.message}`, color: 'red', icon: <IconX size={14} /> });
    } finally { setBuilding(false); }
  }

  return (
    <Stack gap="lg">
      <Text size="sm" c="dimmed">
        Compose a curated lineup. Pick which genres and decades are in play, then check the specific channels you want —
        tighter cuts (90s Comedy, blends, a studio or director) feel more hand-programmed than one broad “Comedy”.
      </Text>

      {/* AI toggle — at the top so the per-pick ✨ on broad/decade picks is discoverable. */}
      <Card withBorder p="sm" style={{ borderColor: aiExtras ? 'var(--mantine-color-grape-6)' : undefined }}>
        <Switch color="grape" checked={aiExtras}
          onChange={(e) => { const v = e.currentTarget.checked; setAiExtras(v); if (!v) patch({ curate: {} }); }}
          label={<Text size="sm" fw={600}>✨ Bring in AI (optional)</Text>}
          description="Adds an AI step after building — discover channels your picks miss, and split broad pools by tone. With this ON, a grape ✨ appears on each checked broad-genre or decade pick; tap it to hand that pool to the AI instead of building it as one channel." />
      </Card>

      {/* Commercials — between-show filler, applied to every channel built here. */}
      <Card withBorder p="sm" style={{ borderColor: commEnabled ? 'var(--mantine-color-orange-6)' : undefined }}>
        <Switch color="orange" checked={commEnabled}
          onChange={(e) => { const v = e.currentTarget.checked; setCommEnabled(v); if (v && !commListId && fillerLists.length) setCommListId(fillerLists[0].id); }}
          label={<Group gap={6}><IconDeviceTv size={15} /><Text size="sm" fw={600}>📺 Add commercials</Text></Group>}
          description="Plays clips from a Tunarr filler list in a short gap between shows — like real TV. Applies to every channel you build here; tune any of them later on the Channels page." />
        {commEnabled && (
          fillerLists.length === 0 ? (
            <Text size="xs" c="yellow.4" mt="xs">
              No filler lists found in Tunarr — create one first (a library of commercial / bumper clips), then reopen this.
            </Text>
          ) : (
            <Group grow mt="xs" align="start">
              <Select label="Filler list" size="xs"
                data={fillerLists.map(fl => ({ value: fl.id, label: `${fl.name} (${fl.contentCount})` }))}
                value={commListId} onChange={setCommListId} allowDeselect={false} />
              <Select label="Break length" size="xs"
                data={[{ value: '5', label: 'Short (~3 min)' }, { value: '30', label: 'Long (~8 min)' }]}
                value={commPad} onChange={(v) => setCommPad(v || '5')} allowDeselect={false} />
            </Group>
          )
        )}
      </Card>

      {/* Auto-update — mark channels live so they refresh as the library grows. */}
      <Card withBorder p="sm" style={{ borderColor: autoUpdate ? 'var(--mantine-color-teal-6)' : undefined }}>
        <Switch color="teal" checked={autoUpdate}
          onChange={(e) => setAutoUpdate(e.currentTarget.checked)}
          label={<Group gap={6}><IconRefresh size={15} /><Text size="sm" fw={600}>🔄 Keep channels fresh (auto-update)</Text></Group>}
          description="Marks these channels to auto-update — new episodes and matching films appear on their own as your library grows, no redeploy. Runs on a schedule (enable the live updater in Settings)." />
      </Card>

      {/* Ingredients */}
      <Card withBorder p="md">
        <Text fw={700} mb={4}>Genres in play</Text>
        <Group gap="xs" mb="xs">
          {(f.genres?.canonical ?? []).map(g => (
            <Chip key={g.tag} size="sm" color="orange" variant="outline" checked={activeGenreTags.has(g.tag)} onChange={() => toggleGenre(g.tag)}>
              {g.display} <Text span c="dimmed" size="xs">({g.count})</Text>
            </Chip>
          ))}
        </Group>
        {(f.genres?.more ?? []).length > 0 && (
          <>
            <Button variant="subtle" size="xs" color="gray" px={4}
              rightSection={<IconChevronDown size={13} style={{ transform: showMore ? 'rotate(180deg)' : undefined, transition: 'transform .15s' }} />}
              onClick={() => setShowMore(v => !v)}>More genres ({(f.genres?.more ?? []).length})</Button>
            <Collapse in={showMore}>
              <Group gap="xs" mt="xs">
                {(f.genres?.more ?? []).map(g => (
                  <Chip key={g.tag} size="sm" color="orange" variant="outline" checked={activeGenreTags.has(g.tag)} onChange={() => toggleGenre(g.tag)}>
                    {g.display} <Text span c="dimmed" size="xs">({g.count})</Text>
                  </Chip>
                ))}
              </Group>
            </Collapse>
          </>
        )}
        <Divider my="sm" />
        <Text fw={700} mb={4}>Decades in play</Text>
        <Group gap="xs">
          {(f.decades ?? []).map(d => (
            <Chip key={d.label} size="sm" color="orange" variant="outline" checked={activeDecadeLabels.has(d.label)} onChange={() => toggleDecade(d.label)}>
              {d.label} <Text span c="dimmed" size="xs">({d.count})</Text>
            </Chip>
          ))}
        </Group>
      </Card>

      {/* TV channels — lowest channel numbers, so they lead. Marathons (~10s) then blocks (~20s). */}
      {((f.marathons?.length ?? 0) > 0 || (f.tv_genres?.length ?? 0) > 0) && (
        <Box>
          <Text fw={700} size="sm" mb={6}>TV channels</Text>
          <Stack gap="sm">
            {(f.marathons?.length ?? 0) > 0 && (() => {
              const items: AddItem[] = f.marathons!.map(m => ({ id: cid.marathon(m.title), spec: { kind: 'marathon', value: m.title, name: `${m.title} Marathon` } }));
              return (
                <CollapsibleSection title="Marathons — one channel per show" count={f.marathons!.length}
                  selectedCount={countSel(items.map(i => i.id))} addItems={items} onAdd={addMany}>
                  {f.marathons!.map((m, i) => (
                    <CandRow key={items[i].id} id={items[i].id} count={m.episodes} label={m.title} checked={isSel(items[i].id)}
                      onToggle={() => toggleSel(items[i].id, items[i].spec)} />
                  ))}
                </CollapsibleSection>
              );
            })()}
            {(f.tv_genres?.length ?? 0) > 0 && (() => {
              const items: AddItem[] = f.tv_genres!.map(t => ({ id: cid.tv(t.genre), spec: { kind: 'tv_genre', genre: t.genre, name: `${t.genre} TV` } }));
              return (
                <CollapsibleSection title="Genre blocks — themed multi-show" count={f.tv_genres!.length}
                  selectedCount={countSel(items.map(i => i.id))} addItems={items} onAdd={addMany}>
                  {f.tv_genres!.map((t, i) => (
                    <CandRow key={items[i].id} id={items[i].id} count={t.count} label={`${t.genre} TV`} checked={isSel(items[i].id)}
                      onToggle={() => toggleSel(items[i].id, items[i].spec)} />
                  ))}
                </CollapsibleSection>
              );
            })()}
          </Stack>
        </Box>
      )}

      {/* Movie channels (~30s) */}
      <Box>
        <Group justify="space-between" mb={6}>
          <Text fw={700} size="sm">Movie channels</Text>
          {aiExtras && activeGenreTags.size > 0 && (
            <Text size="xs" c="grape.4">✨ tap the sparkle on a checked genre/decade pick to let AI split it by tone</Text>
          )}
        </Group>
        {activeGenreTags.size === 0 ? (
          <Text size="sm" c="dimmed">Pick some genres above to see movie channel candidates.</Text>
        ) : (
          <Stack gap="sm">
            {(f.decades ?? []).filter(d => activeDecadeLabels.has(d.label) && genreDecadeByDecade[d.label]?.length).map(d => {
              const cells = genreDecadeByDecade[d.label];
              const items: AddItem[] = cells.map(c => ({ id: cid.gd(c.genre, c.decade_start), spec: { kind: 'genre_decade', genre: c.genre, decade_start: c.decade_start, name: gdName(c.decade_label, c.display) } }));
              return (
                <CollapsibleSection key={d.label} title={d.label} count={cells.length}
                  selectedCount={countSel(items.map(i => i.id))} addItems={items} onAdd={addMany}>
                  {cells.map((c, i) => (
                    <CandRow key={items[i].id} id={items[i].id} count={c.count} label={gdName(c.decade_label, c.display)} checked={isSel(items[i].id)}
                      onToggle={() => toggleSel(items[i].id, items[i].spec)}
                      curatable={aiExtras} curate={isCurate(items[i].id)} onCurate={() => toggleCurate(items[i].id)} />
                  ))}
                </CollapsibleSection>
              );
            })}

            {subGenres.length > 0 && (() => {
              const items: AddItem[] = subGenres.map(x => ({ id: cid.blend(x.blend.genres[0], x.blend.genres[1]), spec: { kind: 'blend', genres: x.blend.genres, name: x.s.name } }));
              return (
                <CollapsibleSection title="Sub-genres" count={subGenres.length}
                  selectedCount={countSel(items.map(i => i.id))} addItems={items} onAdd={addMany}>
                  {subGenres.map(({ s, blend }, i) => (
                    <CandRow key={items[i].id} id={items[i].id} count={blend.count} label={s.name} checked={isSel(items[i].id)}
                      onToggle={() => toggleSel(items[i].id, items[i].spec)} />
                  ))}
                </CollapsibleSection>
              );
            })()}

            {(() => {
              const items: AddItem[] = broadCands.map(g => ({ id: cid.genre(g.tag), spec: { kind: 'genre', genre: g.tag, name: `${g.display} Movies` } }));
              return (
                <CollapsibleSection title="Broad genres" count={broadCands.length}
                  selectedCount={countSel(items.map(i => i.id))} addItems={items} onAdd={addMany}>
                  {broadCands.map((g, i) => (
                    <CandRow key={items[i].id} id={items[i].id} count={g.count} label={`${g.display} Movies`} checked={isSel(items[i].id)}
                      onToggle={() => toggleSel(items[i].id, items[i].spec)}
                      curatable={aiExtras} curate={isCurate(items[i].id)} onCurate={() => toggleCurate(items[i].id)} />
                  ))}
                </CollapsibleSection>
              );
            })()}
          </Stack>
        )}
      </Box>

      {/* Entities (~50s) */}
      {((f.studios?.length ?? 0) > 0 || (f.directors?.length ?? 0) > 0 || (f.actors?.length ?? 0) > 0) && (
        <Box>
          <Text fw={700} size="sm" mb={6}>Studios, directors &amp; actors</Text>
          <Stack gap="sm">
            {(f.studios?.length ?? 0) > 0 && <EntitySection title="Studios" kind="studio" items={f.studios!} makeId={cid.studio} makeName={(v) => v} isSel={isSel} onToggle={toggleSel} onAddMany={addMany} />}
            {(f.directors?.length ?? 0) > 0 && <EntitySection title="Directors" kind="director" items={f.directors!} makeId={cid.director} makeName={(v) => `Directed by ${v}`} isSel={isSel} onToggle={toggleSel} onAddMany={addMany} />}
            {(f.actors?.length ?? 0) > 0 && <EntitySection title="Actors" kind="actor" items={f.actors!} makeId={cid.actor} makeName={(v) => `${v} Movies`} isSel={isSel} onToggle={toggleSel} onAddMany={addMany} />}
          </Stack>
        </Box>
      )}

      {/* Build bar */}
      <Card withBorder p="md">
        <Group justify="space-between">
          <Box>
            <Text size="sm" fw={600}>{exactSpecs.length} channel{exactSpecs.length !== 1 ? 's' : ''} to build · start at #{setup.start}</Text>
            {curateCount > 0 && <Text size="xs" c="grape.4">+ {curateCount} pool{curateCount !== 1 ? 's' : ''} for AI to split by tone</Text>}
          </Box>
          <Group gap="xs">
            {selectedCount > 0 && <Button variant="subtle" size="xs" color="gray" onClick={() => patch({ selected: {}, curate: {} })}>Clear</Button>}
            <Button color="orange" leftSection={<IconWand size={15} />} disabled={selectedCount === 0 && !aiExtras} loading={building} onClick={build}>
              {exactSpecs.length === 0 ? 'Continue to AI' : `Build ${exactSpecs.length} Channel${exactSpecs.length !== 1 ? 's' : ''}`}
            </Button>
          </Group>
        </Group>
      </Card>
    </Stack>
  );
}

// Human description of a curate pool, handed to the AI to split by tone.
function curatePoolDescription(spec: CandidateSpec): string {
  if (spec.kind === 'genre_decade' && spec.decade_start) {
    return `${spec.name} — "${spec.genre}"-tagged movies from ${spec.decade_start}–${spec.decade_start + 9}`;
  }
  return `${spec.name} — all "${spec.genre}"-tagged movies`;
}

// ── AI Extras — discover additional channels, merged on top ──────────────────────

function DiscoverStep({ discover, curatePools, onDone }: { discover: boolean; curatePools: string[]; onDone: () => void }) {
  const [prompt, setPrompt] = useState('');
  const [csvInfo, setCsvInfo] = useState<any>(null);
  const [existingCount, setExistingCount] = useState(0);
  const [pasteText, setPasteText] = useState('');
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<ValidateResult | null>(null);

  useEffect(() => {
    api.getCsvInfo().then(setCsvInfo).catch(() => {});
    api.getDiscoverPrompt(discover, curatePools).then(p => { setPrompt(p.content); setExistingCount(p.existing_count); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function copyPrompt() {
    await copyText(prompt, 'Prompt copied');
  }
  async function validatePaste() {
    if (!pasteText.trim()) return;
    setValidating(true); setResult(await api.validateText(pasteText, true)); setValidating(false);
  }
  async function handleFileDrop(files: File[]) {
    setValidating(true); setResult(await api.validateFile(files[0], true)); setValidating(false);
  }

  function Step({ n, children }: { n: number; children: React.ReactNode }) {
    return (
      <Group gap="sm" wrap="nowrap" align="flex-start">
        <ThemeIcon color="grape" variant="light" radius="xl" size="md" style={{ flexShrink: 0 }}>
          <Text size="xs" fw={700}>{n}</Text>
        </ThemeIcon>
        <Box style={{ flex: 1, minWidth: 0 }}>{children}</Box>
      </Group>
    );
  }

  return (
    <Stack gap="lg">
      <Alert color="grape" variant="light" icon={<IconRobot size={16} />}>
        You've built {existingCount} channel{existingCount !== 1 ? 's' : ''} deterministically. This prompt asks an AI to{' '}
        {curatePools.length > 0 && <b>split your {curatePools.length} flagged pool{curatePools.length !== 1 ? 's' : ''} by tone</b>}
        {curatePools.length > 0 && discover && ' and '}
        {discover && <b>discover extra themed channels your filters miss</b>}
        {!discover && curatePools.length === 0 && 'add channels'}. Paste its answer back and it merges on top. Skip anytime.
      </Alert>

      <Card withBorder p="lg">
        <Stack gap="lg">
          <Step n={1}>
            <Group justify="space-between" wrap="nowrap">
              <Text size="sm" fw={600}>Copy the prompt</Text>
              <Button size="xs" variant="light" color="grape" leftSection={<IconCopy size={13} />} onClick={copyPrompt} disabled={!prompt}>Copy</Button>
            </Group>
            <ScrollArea h={160} mt="xs" style={{ backgroundColor: '#0d0e0f', borderRadius: 4, border: '1px solid var(--mantine-color-dark-4)' }}>
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
            {csvInfo?.exists ? (
              <Button component="a" href="/api/pipeline/csv" download="plex_library.csv" leftSection={<IconDownload size={14} />} color="grape" variant="light" size="xs">
                Download plex_library.csv ({csvInfo.rows?.toLocaleString()} titles)
              </Button>
            ) : (
              <Alert color="yellow" variant="light" icon={<IconAlertCircle size={14} />}>Run Export first to generate the library file.</Alert>
            )}
          </Step>

          <Step n={4}>
            <Text size="sm" fw={600}>Copy the AI's channel list — the JSON only</Text>
            <Text size="xs" c="dimmed">Just the channel lines (one <Code>{'{"number": …}'}</Code> per line). Skip any intro or commentary.</Text>
          </Step>

          <Step n={5}>
            <Text size="sm" fw={600} mb="xs">Paste it back — it merges on top</Text>
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
                {pasteText && !result && <Button color="grape" onClick={validatePaste} loading={validating} style={{ alignSelf: 'flex-start' }}>Merge channels</Button>}
              </Stack>
            ) : (
              <Text size="sm" c="green.4">
                ✓ {result.added ?? 0} channel{(result.added ?? 0) !== 1 ? 's' : ''} merged in.
                {(result.skipped_dupes ?? 0) > 0 && <Text span c="yellow.5"> {result.skipped_dupes} skipped as duplicate{result.skipped_dupes !== 1 ? 's' : ''}.</Text>}
              </Text>
            )}
          </Step>
        </Stack>
      </Card>

      <Group>
        {result?.ok ? (
          <Button color="grape" rightSection={<IconArrowRight size={15} />} onClick={onDone}>
            Continue ({result.count} channels total)
          </Button>
        ) : (
          <Button variant="subtle" color="gray" onClick={onDone}>Skip — deploy what I built</Button>
        )}
      </Group>
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

  useEffect(() => {
    Promise.all([
      api.getChannels().catch(() => ({ channels: [] as { number: number }[] })),
      api.getCollections(),
    ])
      .then(([chFile, cols]) => {
        // Append collections ABOVE the current lineup so they never collide with the
        // channels just composed (plus any AI extras merged on top). apply_collections
        // keeps everything below the lowest collection number, so a base above the max
        // preserves the whole built lineup.
        const maxNum = (chFile.channels ?? []).reduce((m: number, c: { number: number }) => Math.max(m, c.number ?? 0), 0);
        const base = Math.max(start, Math.ceil((maxNum + 1) / 10) * 10);
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
                    onClick={() => copyText(xmltvUrl, 'XMLTV URL copied')}>
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
  loaded: false, facets: null, activeGenres: {}, activeDecades: {}, selected: {}, curate: {},
};

export default function Run() {
  const [step, setStep] = useState(0);
  const [setup, setSetup] = useState<SetupState>({
    method: 'build', includeCollections: false, fetchArt: false, protectedNums: [], start: 1,
  });
  const [planner, setPlanner] = useState<PlannerState>(blankPlanner);
  const [aiExtras, setAiExtras] = useState(false);

  const { method, includeCollections } = setup;

  // Pools the user flagged for AI tonal-splitting (✨ on a broad/decade pick).
  const curatePools = Object.entries(planner.selected)
    .filter(([id]) => planner.curate[id])
    .map(([, spec]) => curatePoolDescription(spec));

  // Build the ordered step list for this method.
  const steps: { key: string; label: string; desc: string }[] = [
    { key: 'setup', label: 'Setup', desc: 'Choose your approach' },
  ];
  if (method !== 'collections') {
    steps.push({ key: 'export', label: 'Export', desc: 'Scan your library' });
    steps.push({ key: 'planner', label: 'Planner', desc: 'Compose your lineup' });
    if (aiExtras) steps.push({ key: 'discover', label: 'AI Extras', desc: 'Discover & curate' });
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

      <Stepper active={step} onStepClick={(s) => { if (s < step) setStep(s); }} color="orange" size="sm">
        {steps.map(s => (
          <Stepper.Step key={s.key} label={s.label} description={s.desc}>
            <Box mt="lg">
              {s.key === 'setup' && <SetupStep setup={setup} onChange={patchSetup} onDone={next} />}
              {s.key === 'export' && <ExportStep onDone={next} />}
              {s.key === 'planner' && <PlannerStep planner={planner} setPlanner={setPlanner} setup={setup} aiExtras={aiExtras} setAiExtras={setAiExtras} onDone={next} />}
              {s.key === 'discover' && <DiscoverStep discover curatePools={curatePools} onDone={next} />}
              {s.key === 'collections' && <CollectionsStep start={setup.start} onDone={next} />}
              {s.key === 'deploy' && <DeployStep setup={setup} />}
            </Box>
          </Stepper.Step>
        ))}
      </Stepper>
    </Stack>
  );
}
