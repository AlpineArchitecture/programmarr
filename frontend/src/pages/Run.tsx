import {
  Alert, Anchor, Box, Button, Card, Center, Checkbox, Divider, Group,
  Image, Loader, NumberInput, ScrollArea, SimpleGrid, Stack, Stepper,
  Tabs, Text, Textarea, ThemeIcon, Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Dropzone } from '@mantine/dropzone';
import {
  IconAlertCircle, IconArrowRight, IconCheck, IconCopy, IconDownload,
  IconExternalLink, IconPlayerPlay, IconUpload, IconX,
} from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { api, streamPipeline, StreamEvent, PlexCollection, CollectionSelection } from '../api/client';
import type { Channel } from '../api/client';
import TerminalOutput from '../components/TerminalOutput';

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

// ── Step: Export ───────────────────────────────────────────────────────────────

function ExportStep({ onDone }: { onDone: () => void }) {
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [success, setSuccess] = useState(false);
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof api.getCsvInfo>> | null>(null);

  async function run() {
    setLines([]); setDone(false); setSummary(null); setRunning(true);
    try {
      const code = await streamPipeline('/pipeline/export', {}, (ev: StreamEvent) => {
        if (ev.type === 'line') setLines(l => [...l, ev.text]);
      });
      const ok = code === 0;
      setSuccess(ok); setDone(true);
      if (ok) setSummary(await api.getCsvInfo());
    } catch (e: any) {
      setLines(l => [...l, `Error: ${e.message}`]);
      setDone(true); setSuccess(false);
    } finally {
      setRunning(false);
    }
  }

  const skipped = (summary?.skipped_movies ?? 0) + (summary?.skipped_shows ?? 0);

  return (
    <Stack gap="md">
      <Group>
        <Button leftSection={<IconPlayerPlay size={15} />} color="orange" onClick={run} loading={running}>
          {running ? 'Exporting…' : done ? 'Re-run Export' : 'Run Export'}
        </Button>
        {done && !success && <Button variant="subtle" color="red" onClick={run}>Retry</Button>}
      </Group>

      {done && success && summary && (
        <Card withBorder p="sm" bg="dark.8">
          <Group justify="space-between" wrap="nowrap" gap="sm">
            <Group gap="sm" wrap="nowrap">
              <ThemeIcon color="green" variant="light" size="sm" radius="xl" style={{ flexShrink: 0 }}>
                <IconCheck size={12} />
              </ThemeIcon>
              <Text size="sm" fw={600}>
                {summary.movies ?? '—'} movies · {summary.tv_shows ?? '—'} TV shows · {Math.round((summary.size ?? 0) / 1024)} KB
                {skipped > 0 && (
                  <Text span size="sm" c="yellow.4"> · {skipped} skipped (not in Tunarr)</Text>
                )}
              </Text>
            </Group>
            <Button size="xs" color="orange" rightSection={<IconArrowRight size={12} />} onClick={onDone} style={{ flexShrink: 0 }}>
              Continue
            </Button>
          </Group>
        </Card>
      )}

      {(running || done) && <TerminalOutput lines={lines} done={done} success={success} />}
    </Stack>
  );
}

// ── Step: Generate (No-AI) ─────────────────────────────────────────────────────

function GenerateStep({ onDone }: { onDone: () => void }) {
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [success, setSuccess] = useState(false);
  const [channelCount, setChannelCount] = useState<number | null>(null);

  async function run() {
    setLines([]); setDone(false); setChannelCount(null); setRunning(true);
    try {
      const code = await streamPipeline('/pipeline/no-ai', {}, (ev: StreamEvent) => {
        if (ev.type === 'line') setLines(l => [...l, ev.text]);
      });
      const ok = code === 0;
      setSuccess(ok); setDone(true);
      if (ok) {
        try {
          const data = await api.getChannels();
          setChannelCount(data.channels.length);
        } catch { /* non-fatal */ }
      }
    } catch (e: any) {
      setLines(l => [...l, `Error: ${e.message}`]);
      setDone(true); setSuccess(false);
    } finally {
      setRunning(false);
    }
  }

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Automatically generates decade channels, genre channels, and TV marathon channels from your library metadata.
      </Text>
      <Group>
        <Button leftSection={<IconPlayerPlay size={15} />} color="orange" onClick={run} loading={running}>
          {running ? 'Generating…' : done ? 'Re-run Generate' : 'Generate Channels'}
        </Button>
        {done && !success && <Button variant="subtle" color="red" onClick={run}>Retry</Button>}
      </Group>

      {(running || done) && <TerminalOutput lines={lines} done={done} success={success} />}

      {done && success && channelCount !== null && (
        <ResultsCard title={`${channelCount} channels generated`} subtitle="channels.json is ready">
          <Button color="orange" rightSection={<IconArrowRight size={15} />} onClick={onDone}>
            Continue
          </Button>
        </ResultsCard>
      )}
    </Stack>
  );
}

// ── Step: LLM Handoff ──────────────────────────────────────────────────────────

function LLMHandoff({ onAddCollections, onSkipToDeploy }: { onAddCollections: () => void; onSkipToDeploy: () => void }) {
  const [target, setTarget] = useState<number | string>(30);
  const [prefs, setPrefs] = useState('');
  const [prompt, setPrompt] = useState('');
  const [csvInfo, setCsvInfo] = useState<any>(null);
  const [pasteText, setPasteText] = useState('');
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; count?: number; error?: string; channels?: Channel[] } | null>(null);

  const PREFS_MAX = 500;
  const charsLeft = PREFS_MAX - prefs.length;

  useEffect(() => {
    api.getCsvInfo().then(setCsvInfo);
    loadPrompt();
  }, []);

  async function loadPrompt() {
    try {
      const p = await api.getPrompt(String(target), prefs);
      setPrompt(p.content);
    } catch { /* ignore */ }
  }

  async function copyPrompt() {
    await navigator.clipboard.writeText(prompt);
    notifications.show({ message: 'Prompt copied to clipboard', color: 'green', icon: <IconCheck size={14} /> });
  }

  async function validatePaste() {
    if (!pasteText.trim()) return;
    setValidating(true);
    const r = await api.validateText(pasteText);
    setResult(r);
    setValidating(false);
  }

  async function handleFileDrop(files: File[]) {
    setValidating(true);
    const r = await api.validateFile(files[0]);
    setResult(r);
    setValidating(false);
  }

  const breakdown = result?.ok && result.channels ? getChannelBreakdown(result.channels) : null;

  return (
    <Stack gap="lg">
      {/* Config card */}
      <Card withBorder p="md">
        <Text fw={700} mb="sm">Configure your request</Text>
        <Stack gap="sm">
          <Group align="flex-end" gap="md">
            <NumberInput
              label="Target channel count"
              w={100}
              value={target}
              onChange={setTarget}
              onBlur={loadPrompt}
              min={1} max={500} step={1} size="sm"
            />
            <Text size="sm" c="dimmed" mb={6}>channels — the LLM will aim for this number</Text>
          </Group>
          <Textarea
            label="Theme preferences (optional)"
            placeholder="e.g. Batman, 90s cartoons, Documentaries, Classic westerns, Horror films…"
            value={prefs}
            onChange={(e) => setPrefs(e.currentTarget.value)}
            onBlur={loadPrompt}
            maxLength={PREFS_MAX}
            minRows={3}
            autosize
            maxRows={8}
            size="sm"
          />
          <Text size="xs" c={charsLeft < 50 ? 'red.4' : 'dimmed'} ta="right">{charsLeft} chars remaining</Text>
        </Stack>
      </Card>

      {/* Prompt + CSV side by side */}
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        <Card p="md">
          <Group justify="space-between" mb="sm">
            <Text fw={700}>Prompt</Text>
            <Button size="xs" variant="light" color="orange" leftSection={<IconCopy size={13} />} onClick={copyPrompt} disabled={!prompt}>
              Copy
            </Button>
          </Group>
          <ScrollArea h={240} style={{ backgroundColor: '#0d0e0f', borderRadius: 4, border: '1px solid var(--mantine-color-dark-4)' }}>
            <Box p="sm">
              <Text size="xs" style={{ fontFamily: 'ui-monospace, monospace', whiteSpace: 'pre-wrap', color: '#d4d4d4' }}>
                {prompt || 'Generating prompt…'}
              </Text>
            </Box>
          </ScrollArea>
        </Card>

        <Card p="md">
          <Text fw={700} mb="sm">Plex Library CSV</Text>
          {csvInfo?.exists ? (
            <Stack gap="sm">
              <Group gap="lg">
                <Text size="sm" c="dimmed">{csvInfo.rows?.toLocaleString()} titles</Text>
                <Text size="sm" c="dimmed">{Math.round((csvInfo.size || 0) / 1024)} KB</Text>
              </Group>
              <ScrollArea h={180} style={{ backgroundColor: '#0d0e0f', borderRadius: 4, border: '1px solid var(--mantine-color-dark-4)' }}>
                <Box p="sm">
                  {(csvInfo.preview || []).map((line: string, i: number) => (
                    <Text key={i} size="xs" style={{ fontFamily: 'ui-monospace, monospace', color: i === 0 ? 'var(--mantine-color-orange-4)' : '#d4d4d4' }}>
                      {line}
                    </Text>
                  ))}
                </Box>
              </ScrollArea>
              <Button component="a" href="/api/pipeline/csv" download="plex_library.csv" leftSection={<IconDownload size={15} />} color="orange" variant="light" size="sm" style={{ alignSelf: 'flex-start' }}>
                Download CSV
              </Button>
            </Stack>
          ) : (
            <Alert color="yellow" icon={<IconAlertCircle size={16} />} variant="light">
              Run Export first to generate plex_library.csv
            </Alert>
          )}
        </Card>
      </SimpleGrid>

      {/* LLM result */}
      {!result?.ok && (
        <Card p="md">
          <Text fw={700} mb="sm">LLM Result</Text>
          <Text size="sm" c="dimmed" mb="md">Paste the LLM output below, or drag and drop the file.</Text>
          <Stack gap="sm">
            <Textarea
              placeholder="Paste channels JSON or JSONL here…"
              minRows={6}
              autosize
              maxRows={14}
              value={pasteText}
              onChange={(e) => { setPasteText(e.currentTarget.value); setResult(null); }}
              styles={{ input: { fontFamily: 'ui-monospace, monospace', fontSize: 12 } }}
            />
            <Text size="xs" c="dimmed" ta="center">— or —</Text>
            <Dropzone
              onDrop={handleFileDrop}
              accept={{ 'application/json': ['.json'], 'text/plain': ['.jsonl', '.txt'] }}
              maxFiles={1}
              loading={validating}
              styles={{ root: { borderColor: 'var(--mantine-color-dark-4)' } }}
            >
              <Group justify="center" gap="sm" py="sm">
                <IconUpload size={18} color="var(--mantine-color-dimmed)" />
                <Text size="sm" c="dimmed">Drop channels.json / .jsonl here</Text>
              </Group>
            </Dropzone>
            {result && !result.ok && (
              <Alert color="red" icon={<IconX size={16} />} variant="light">
                Invalid — {result.error}
              </Alert>
            )}
            {pasteText && !result && (
              <Button color="orange" onClick={validatePaste} loading={validating} style={{ alignSelf: 'flex-start' }}>
                Validate &amp; Save
              </Button>
            )}
          </Stack>
        </Card>
      )}

      {/* Validation success card */}
      {result?.ok && breakdown && (
        <ResultsCard
          title={`${result.count} channels loaded`}
          subtitle={`${breakdown.totalContent} content items · saved to channels.json`}
        >
          <SimpleGrid cols={{ base: 2, sm: 3 }} mb="md">
            {breakdown.marathons > 0 && <StatBox label="TV Marathons (10–19)" value={breakdown.marathons} />}
            {breakdown.tvBlocks > 0 && <StatBox label="TV Blocks (20–29)" value={breakdown.tvBlocks} />}
            {breakdown.movies > 0 && <StatBox label="Movies (30–49)" value={breakdown.movies} />}
            {breakdown.franchise > 0 && <StatBox label="Franchise (50–69)" value={breakdown.franchise} />}
            {breakdown.specialty > 0 && <StatBox label="Specialty (70–79)" value={breakdown.specialty} />}
            {breakdown.collections > 0 && <StatBox label="Collections (80+)" value={breakdown.collections} />}
          </SimpleGrid>
          <Divider mb="md" />
          <Group>
            <Button color="orange" rightSection={<IconArrowRight size={15} />} onClick={onAddCollections}>
              Add Plex Collections
            </Button>
            <Button variant="subtle" color="gray" onClick={onSkipToDeploy}>
              Skip to Deploy
            </Button>
            <Button variant="subtle" size="xs" color="dimmed" onClick={() => setResult(null)}>
              Replace channels.json
            </Button>
          </Group>
        </ResultsCard>
      )}
    </Stack>
  );
}

// ── Step: Collections ──────────────────────────────────────────────────────────

type CollectionSel = { id: string; name: string; channel_number: number; include: boolean };

function CollectionsStep({ onDone }: { onDone: () => void }) {
  const [collections, setCollections] = useState<PlexCollection[]>([]);
  const [selections, setSelections] = useState<CollectionSel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    api.getCollections()
      .then(cols => {
        setCollections(cols);
        setSelections(cols.map((c, i) => ({ id: c.id, name: c.name, channel_number: 80 + i, include: true })));
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  function updateSel(idx: number, patch: Partial<CollectionSel>) {
    setSelections(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s));
  }

  async function apply() {
    setApplying(true);
    try {
      const payload: CollectionSelection[] = selections.map(s => ({
        name: s.name,
        channel_number: s.channel_number,
        include: s.include,
      }));
      const r = await api.applyCollections(payload);
      notifications.show({
        message: `${r.added} collection${r.added !== 1 ? 's' : ''} added to channels.json`,
        color: 'green',
        icon: <IconCheck size={14} />,
      });
      onDone();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setApplying(false);
    }
  }

  if (loading) {
    return (
      <Center py="xl">
        <Stack align="center" gap="sm">
          <Loader color="orange" />
          <Text size="sm" c="dimmed">Fetching collections from Plex…</Text>
        </Stack>
      </Center>
    );
  }

  if (error) {
    return (
      <Alert color="red" icon={<IconX size={16} />} variant="light">
        {error}
        <Button variant="subtle" size="xs" mt="xs" onClick={onDone}>Skip Collections</Button>
      </Alert>
    );
  }

  if (collections.length === 0) {
    return (
      <Stack gap="md">
        <Alert color="yellow" icon={<IconAlertCircle size={16} />} variant="light">
          No collections found in your Plex library.
        </Alert>
        <Button variant="subtle" color="gray" onClick={onDone}>Continue to Deploy</Button>
      </Stack>
    );
  }

  const includedCount = selections.filter(s => s.include).length;

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" c="dimmed">{collections.length} collections — select which to include as channels.</Text>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          <Button size="xs" variant="subtle" onClick={() => setSelections(s => s.map(x => ({ ...x, include: true })))}>All</Button>
          <Button size="xs" variant="subtle" onClick={() => setSelections(s => s.map(x => ({ ...x, include: false })))}>None</Button>
          <Button
            size="sm" color="orange"
            onClick={apply} loading={applying} disabled={includedCount === 0}
            rightSection={<IconArrowRight size={13} />}
          >
            Add {includedCount}
          </Button>
          <Button variant="subtle" color="gray" size="sm" onClick={onDone}>Skip</Button>
        </Group>
      </Group>

      <Stack gap={0} style={{ border: '1px solid var(--mantine-color-dark-4)', borderRadius: 8, overflow: 'hidden' }}>
        {collections.map((col, idx) => {
          const sel = selections[idx];
          if (!sel) return null;
          return (
            <Group
              key={col.id}
              gap="sm"
              wrap="nowrap"
              px="md"
              py={6}
              style={{
                borderBottom: idx < collections.length - 1 ? '1px solid var(--mantine-color-dark-6)' : undefined,
                opacity: sel.include ? 1 : 0.4,
                transition: 'opacity 0.15s',
              }}
            >
              <Checkbox
                checked={sel.include}
                onChange={(e) => updateSel(idx, { include: e.currentTarget.checked })}
                style={{ flexShrink: 0 }}
              />
              <Image
                src={`/api/pipeline/collections/${col.id}/poster`}
                w={28} h={42}
                radius="sm"
                fit="cover"
                style={{ flexShrink: 0 }}
                fallbackSrc="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='28' height='42'%3E%3Crect width='28' height='42' fill='%23333'/%3E%3C/svg%3E"
              />
              <NumberInput
                value={sel.channel_number}
                onChange={(v) => {
                  const n = typeof v === 'number' ? v : parseInt(String(v));
                  if (!isNaN(n)) updateSel(idx, { channel_number: n });
                }}
                min={1} max={999} size="xs" w={68}
                disabled={!sel.include}
                styles={{ input: { textAlign: 'center', paddingInline: 4 } }}
              />
              <Box style={{ flex: 1, minWidth: 0 }}>
                <Text fw={600} size="sm" lineClamp={1}>{col.name}</Text>
                <Text size="xs" c="dimmed">{col.section} · {col.count} items</Text>
              </Box>
            </Group>
          );
        })}
      </Stack>

      <Group>
        <Button
          color="orange"
          onClick={apply}
          loading={applying}
          disabled={includedCount === 0}
          rightSection={<IconArrowRight size={15} />}
        >
          Add {includedCount} Collection{includedCount !== 1 ? 's' : ''}
        </Button>
        <Button variant="subtle" color="gray" onClick={onDone}>Skip Collections</Button>
      </Group>
    </Stack>
  );
}

// ── Probe channel parsing ──────────────────────────────────────────────────────

type ChannelSel = { number: number; deployNumber: number; name: string; summary: string; include: boolean };

function parseProbeChannels(lines: string[]): ChannelSel[] {
  return lines
    .map(line => {
      const m = line.match(/\[PROBE\] #(\d+) (.+?) \| shuffle=\w+ \| (.+)/);
      return m ? {
        number: parseInt(m[1]),
        deployNumber: parseInt(m[1]),
        name: m[2].trim(),
        summary: m[3].trim(),
        include: true,
      } : null;
    })
    .filter(Boolean) as ChannelSel[];
}

// ── Step: Deploy ───────────────────────────────────────────────────────────────

function DeployStep({ onDone, onSkipToSync }: { onDone: () => void; onSkipToSync: () => void }) {
  const [probeLines, setProbeLines] = useState<string[]>([]);
  const [probeDone, setProbeDone] = useState(false);
  const [probeOk, setProbeOk] = useState(false);
  const [probing, setProbing] = useState(false);
  const [channelSels, setChannelSels] = useState<ChannelSel[]>([]);

  const [deployLines, setDeployLines] = useState<string[]>([]);
  const [deployDone, setDeployDone] = useState(false);
  const [deployOk, setDeployOk] = useState(false);
  const [deploying, setDeploying] = useState(false);

  const [config, setConfig] = useState<Record<string, string>>({});

  useEffect(() => { api.getConfig().then(setConfig); }, []);

  useEffect(() => {
    if (probeDone && probeOk) {
      setChannelSels(parseProbeChannels(probeLines));
    }
  }, [probeDone, probeOk]);

  async function runProbe() {
    setProbeLines([]); setProbeDone(false); setChannelSels([]); setProbing(true);
    const code = await streamPipeline('/pipeline/probe', {}, (ev: StreamEvent) => {
      if (ev.type === 'line') setProbeLines(l => [...l, ev.text]);
    });
    setProbeOk(code === 0); setProbeDone(true); setProbing(false);
  }

  async function runDeploy() {
    setDeployLines([]); setDeployDone(false); setDeploying(true);
    const ev = (e: StreamEvent) => { if (e.type === 'line') setDeployLines(l => [...l, e.text]); };
    let code: number;
    if (channelSels.length > 0) {
      const body = channelSels.map(s => ({
        original_number: s.number,
        deploy_number: s.deployNumber,
        include: s.include,
      }));
      code = await streamPipeline('/pipeline/deploy-selective', {}, ev, body);
    } else {
      code = await streamPipeline('/pipeline/deploy', {}, ev);
    }
    setDeployOk(code === 0); setDeployDone(true); setDeploying(false);
  }

  function updateChannelSel(idx: number, patch: Partial<ChannelSel>) {
    setChannelSels(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s));
  }

  const deployStats = parseRunStats(deployLines);
  const includedCount = channelSels.filter(s => s.include).length;
  const tunarrUrl = config.tunarr_url || '';
  const plexLiveTvUrl = config.plex_url ? `${config.plex_url.replace(/\/$/, '')}/web/index.html#!/settings/livetv` : '';

  return (
    <Stack gap="lg">
      {/* Probe */}
      <Card withBorder p="lg">
        <Text fw={700} size="lg" mb="xs">Step 1 — Dry Run</Text>
        <Text size="sm" c="dimmed" mb="md">
          Before anything touches Tunarr, we verify every title in your channels.json exists in your library.
          You'll see exactly what gets created — no changes are made until you hit Deploy.
        </Text>
        <Group mb="sm">
          <Button
            color="gray" variant="light"
            leftSection={<IconPlayerPlay size={15} />}
            onClick={runProbe} loading={probing}
          >
            {probing ? 'Running probe…' : probeDone ? 'Re-run Probe' : 'Run Probe'}
          </Button>
        </Group>

        {(probing || probeDone) && (
          probeDone && probeOk && channelSels.length > 0 ? (
            <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" mt="sm">
              <TerminalOutput lines={probeLines} done={probeDone} success={probeOk} height={320} />
              <Card withBorder p="sm" style={{ display: 'flex', flexDirection: 'column', height: 320 }}>
                <Group justify="space-between" mb="xs">
                  <Group gap="xs">
                    <ThemeIcon color="green" variant="light" size="sm" radius="xl">
                      <IconCheck size={12} />
                    </ThemeIcon>
                    <Text size="sm" fw={600}>{channelSels.length} channels — review before deploying</Text>
                  </Group>
                  <Group gap={4}>
                    <Button size="xs" variant="subtle" py={2} onClick={() => setChannelSels(s => s.map(x => ({ ...x, include: true })))}>All</Button>
                    <Button size="xs" variant="subtle" py={2} onClick={() => setChannelSels(s => s.map(x => ({ ...x, include: false })))}>None</Button>
                  </Group>
                </Group>
                <ScrollArea style={{ flex: 1 }}>
                  <Stack gap={0}>
                    {channelSels.map((sel, idx) => (
                      <Group
                        key={sel.number}
                        gap="xs"
                        wrap="nowrap"
                        py={5}
                        px={4}
                        style={{
                          borderBottom: '1px solid var(--mantine-color-dark-6)',
                          opacity: sel.include ? 1 : 0.4,
                          transition: 'opacity 0.1s',
                        }}
                      >
                        <Checkbox
                          size="xs"
                          checked={sel.include}
                          onChange={(e) => updateChannelSel(idx, { include: e.currentTarget.checked })}
                          style={{ flexShrink: 0 }}
                        />
                        <NumberInput
                          value={sel.deployNumber}
                          onChange={(v) => {
                            const n = typeof v === 'number' ? v : parseInt(String(v));
                            if (!isNaN(n)) updateChannelSel(idx, { deployNumber: n });
                          }}
                          min={1} max={999} size="xs" w={58}
                          disabled={!sel.include}
                          styles={{ input: { textAlign: 'center', paddingInline: 4 } }}
                        />
                        <Text size="xs" style={{ flex: 1, minWidth: 0 }} lineClamp={1}>{sel.name}</Text>
                        <Text size="xs" c="dimmed" style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>{sel.summary}</Text>
                      </Group>
                    ))}
                  </Stack>
                </ScrollArea>
              </Card>
            </SimpleGrid>
          ) : (
            <TerminalOutput lines={probeLines} done={probeDone} success={probeOk} />
          )
        )}

        {probeDone && !probeOk && (
          <Alert color="red" variant="light" icon={<IconX size={16} />} mt="md">
            Probe reported errors — check the output above and fix your channels.json before deploying.
          </Alert>
        )}
      </Card>

      <Divider />

      {/* Deploy */}
      <Card withBorder p="lg">
        <Text fw={700} size="lg" mb="xs">Step 2 — Deploy</Text>
        <Text size="sm" c="dimmed" mb="md">
          Replaces your existing Tunarr channels with the new lineup. This is the real thing — it writes to Tunarr now.
        </Text>

        {!probeDone && (
          <Alert color="gray" variant="light" icon={<IconAlertCircle size={16} />}>
            Run the probe first to verify your channels before deploying.
          </Alert>
        )}

        {probeDone && !probeOk && (
          <Alert color="red" variant="light" icon={<IconX size={16} />}>
            Fix the probe errors above before deploying.
          </Alert>
        )}

        {probeDone && probeOk && (
          <Group mb="sm">
            <Button
              color="orange"
              leftSection={<IconPlayerPlay size={15} />}
              onClick={runDeploy}
              loading={deploying}
              disabled={deployDone && deployOk || includedCount === 0}
            >
              {deploying ? 'Deploying…'
                : deployDone && deployOk ? 'Deployed'
                : channelSels.length > 0 ? `Deploy ${includedCount} Channel${includedCount !== 1 ? 's' : ''}`
                : 'Deploy to Tunarr'}
            </Button>
            {channelSels.length > 0 && includedCount < channelSels.length && (
              <Text size="xs" c="dimmed">{channelSels.length - includedCount} excluded</Text>
            )}
          </Group>
        )}

        {(deploying || deployDone) && <TerminalOutput lines={deployLines} done={deployDone} success={deployOk} />}

        {deployDone && deployOk && (
          <ResultsCard
            title={`${deployStats.created ?? '?'} channels are live in Tunarr`}
            subtitle="Your lineup has been pushed"
          >
            <Group gap="xl" mb="md">
              <StatBox label="Channels Created" value={deployStats.created ?? '—'} />
              <StatBox label="Channels Skipped" value={deployStats.skipped ?? '—'} />
            </Group>

            {(tunarrUrl || plexLiveTvUrl) && (
              <Group mb="md" gap="sm">
                {tunarrUrl && (
                  <Button
                    component="a" href={tunarrUrl} target="_blank" rel="noreferrer"
                    variant="light" color="blue" size="sm"
                    leftSection={<IconExternalLink size={14} />}
                  >
                    Open Tunarr
                  </Button>
                )}
                {plexLiveTvUrl && (
                  <Button
                    component="a" href={plexLiveTvUrl} target="_blank" rel="noreferrer"
                    variant="light" color="grape" size="sm"
                    leftSection={<IconExternalLink size={14} />}
                  >
                    Open Plex Live TV
                  </Button>
                )}
              </Group>
            )}

            <Divider mb="md" />
            <Text fw={600} mb="sm" size="sm">What's next?</Text>
            <Group>
              <Button color="orange" rightSection={<IconArrowRight size={15} />} onClick={onDone}>
                Fetch Channel Art
              </Button>
              <Button variant="subtle" color="gray" onClick={onSkipToSync}>
                Skip to Sync Plex
              </Button>
            </Group>
          </ResultsCard>
        )}
      </Card>
    </Stack>
  );
}

// ── Step: Skippable (Fetch Images / Sync Plex) ─────────────────────────────────

function SkippableStep({
  title, description, note, label, endpoint, onDone,
}: {
  title: string;
  description: string;
  note?: string;
  label: string;
  endpoint: string;
  onDone: () => void;
}) {
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [success, setSuccess] = useState(false);

  async function run() {
    setLines([]); setDone(false); setRunning(true);
    try {
      const code = await streamPipeline(endpoint, {}, (ev: StreamEvent) => {
        if (ev.type === 'line') setLines(l => [...l, ev.text]);
      });
      const ok = code === 0;
      setSuccess(ok); setDone(true);
      if (ok) onDone();
    } catch (e: any) {
      setLines(l => [...l, `Error: ${e.message}`]);
      setDone(true); setSuccess(false);
    } finally {
      setRunning(false);
    }
  }

  return (
    <Stack gap="md">
      <Card withBorder p="md" bg="dark.8">
        <Text fw={600} mb="xs">{title}</Text>
        <Text size="sm" c="dimmed">{description}</Text>
        {note && <Text size="xs" c="yellow.5" mt="xs">{note}</Text>}
      </Card>
      <Group>
        <Button color="orange" onClick={run} loading={running} leftSection={<IconPlayerPlay size={15} />}>
          {running ? `Running ${label}…` : `Run ${label}`}
        </Button>
        {!running && <Button variant="subtle" color="gray" onClick={onDone}>Skip</Button>}
        {done && !success && <Button variant="subtle" color="red" onClick={run}>Retry</Button>}
      </Group>
      {(running || done) && <TerminalOutput lines={lines} done={done} success={success} />}
    </Stack>
  );
}

// ── Paths ──────────────────────────────────────────────────────────────────────

function AIPath() {
  const [step, setStep] = useState(0);

  return (
    <Stepper active={step} onStepClick={(s) => { if (s < step) setStep(s); }} color="orange" mt="md">
      <Stepper.Step label="Export" description="Fetch Plex library">
        <Box mt="lg"><ExportStep onDone={() => setStep(1)} /></Box>
      </Stepper.Step>

      <Stepper.Step label="LLM Handoff" description="Copy prompt, paste result">
        <Box mt="lg">
          <LLMHandoff onAddCollections={() => setStep(2)} onSkipToDeploy={() => setStep(3)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Collections" description="Optional Plex collections">
        <Box mt="lg"><CollectionsStep onDone={() => setStep(3)} /></Box>
      </Stepper.Step>

      <Stepper.Step label="Deploy" description="Probe & push to Tunarr">
        <Box mt="lg">
          <DeployStep onDone={() => setStep(4)} onSkipToSync={() => setStep(5)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Channel Art" description="Fetch TMDB logos">
        <Box mt="lg">
          <SkippableStep
            title="Fetch Channel Art"
            description="Downloads real show and movie logos from TMDB for solo-title channels (marathons, single-movie specialty channels). Multi-title genre and decade blocks are skipped automatically."
            note="Requires a TMDB API key in Settings."
            label="Fetch Images"
            endpoint="/pipeline/images"
            onDone={() => setStep(5)}
          />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Sync Plex" description="Add channels to Plex DVR">
        <Box mt="lg">
          <SkippableStep
            title="Sync with Plex"
            description="Automatically adds your new Tunarr channels to Plex Live TV & DVR. If auto-sync isn't possible, you'll get step-by-step manual setup instructions."
            label="Sync Plex"
            endpoint="/pipeline/sync"
            onDone={() => setStep(6)}
          />
        </Box>
      </Stepper.Step>

      <Stepper.Completed>
        <Alert color="green" icon={<IconCheck size={16} />} mt="lg" variant="light">
          All done! Your channels are live.{' '}
          <Anchor href="/" size="sm">Head to the Dashboard →</Anchor>
        </Alert>
      </Stepper.Completed>
    </Stepper>
  );
}

function NoAIPath() {
  const [step, setStep] = useState(0);

  return (
    <Stepper active={step} onStepClick={(s) => { if (s < step) setStep(s); }} color="orange" mt="md">
      <Stepper.Step label="Export" description="Fetch Plex library">
        <Box mt="lg"><ExportStep onDone={() => setStep(1)} /></Box>
      </Stepper.Step>

      <Stepper.Step label="Generate" description="Auto-build channels from metadata">
        <Box mt="lg"><GenerateStep onDone={() => setStep(2)} /></Box>
      </Stepper.Step>

      <Stepper.Step label="Collections" description="Optional Plex collections">
        <Box mt="lg"><CollectionsStep onDone={() => setStep(3)} /></Box>
      </Stepper.Step>

      <Stepper.Step label="Deploy" description="Probe & push to Tunarr">
        <Box mt="lg">
          <DeployStep onDone={() => setStep(4)} onSkipToSync={() => setStep(5)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Channel Art" description="Fetch TMDB logos">
        <Box mt="lg">
          <SkippableStep
            title="Fetch Channel Art"
            description="Downloads real show and movie logos from TMDB for solo-title channels."
            note="Requires a TMDB API key in Settings."
            label="Fetch Images"
            endpoint="/pipeline/images"
            onDone={() => setStep(5)}
          />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Sync Plex" description="Add channels to Plex DVR">
        <Box mt="lg">
          <SkippableStep
            title="Sync with Plex"
            description="Automatically adds your new Tunarr channels to Plex Live TV & DVR."
            label="Sync Plex"
            endpoint="/pipeline/sync"
            onDone={() => setStep(6)}
          />
        </Box>
      </Stepper.Step>

      <Stepper.Completed>
        <Alert color="green" icon={<IconCheck size={16} />} mt="lg" variant="light">
          All done! Your channels are live.{' '}
          <Anchor href="/" size="sm">Head to the Dashboard →</Anchor>
        </Alert>
      </Stepper.Completed>
    </Stepper>
  );
}

function CollectionsPath() {
  const [step, setStep] = useState(0);

  return (
    <Stepper active={step} onStepClick={(s) => { if (s < step) setStep(s); }} color="orange" mt="md">
      <Stepper.Step label="Collections" description="Fetch and configure collection channels">
        <Box mt="lg"><CollectionsStep onDone={() => setStep(1)} /></Box>
      </Stepper.Step>

      <Stepper.Step label="Deploy" description="Probe & push to Tunarr">
        <Box mt="lg">
          <DeployStep onDone={() => setStep(2)} onSkipToSync={() => setStep(3)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Channel Art" description="Fetch TMDB logos">
        <Box mt="lg">
          <SkippableStep
            title="Fetch Channel Art"
            description="Downloads real show and movie logos from TMDB for solo-title channels."
            note="Requires a TMDB API key in Settings."
            label="Fetch Images"
            endpoint="/pipeline/images"
            onDone={() => setStep(3)}
          />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Sync Plex" description="Add channels to Plex DVR">
        <Box mt="lg">
          <SkippableStep
            title="Sync with Plex"
            description="Automatically adds your new Tunarr channels to Plex Live TV & DVR."
            label="Sync Plex"
            endpoint="/pipeline/sync"
            onDone={() => setStep(4)}
          />
        </Box>
      </Stepper.Step>

      <Stepper.Completed>
        <Alert color="green" icon={<IconCheck size={16} />} mt="lg" variant="light">
          Collections deployed!{' '}
          <Anchor href="/" size="sm">Head to the Dashboard →</Anchor>
        </Alert>
      </Stepper.Completed>
    </Stepper>
  );
}

// ── Root ───────────────────────────────────────────────────────────────────────

export default function Run() {
  return (
    <Stack gap="lg">
      <Title order={2}>Run Pipeline</Title>

      <Tabs defaultValue="ai" color="orange">
        <Tabs.List>
          <Tabs.Tab value="ai">AI Path</Tabs.Tab>
          <Tabs.Tab value="no-ai">No-AI Path</Tabs.Tab>
          <Tabs.Tab value="collections">Collections Only</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="ai" pt="xs"><AIPath /></Tabs.Panel>
        <Tabs.Panel value="no-ai" pt="xs"><NoAIPath /></Tabs.Panel>
        <Tabs.Panel value="collections" pt="xs"><CollectionsPath /></Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
