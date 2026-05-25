import {
  Alert, Box, Button, Card, Divider, Group,
  NumberInput, ScrollArea, SimpleGrid, Stack, Stepper, Switch,
  Tabs, Text, Textarea, TextInput, Title,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { notifications } from '@mantine/notifications';
import {
  IconAlertCircle, IconCheck, IconCopy, IconDownload,
  IconPlayerPlay, IconUpload, IconX,
} from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';
import { api, streamPipeline, StreamEvent } from '../api/client';
import TerminalOutput from '../components/TerminalOutput';

// ── Shared terminal step component ─────────────────────────────────────────────

function RunStep({
  label, endpoint, params = {}, onDone,
}: {
  label: string;
  endpoint: string;
  params?: Record<string, string>;
  onDone?: (success: boolean) => void;
}) {
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [success, setSuccess] = useState(false);

  async function run() {
    setLines([]);
    setDone(false);
    setRunning(true);
    try {
      const code = await streamPipeline(endpoint, params, (ev: StreamEvent) => {
        if (ev.type === 'line') setLines((l) => [...l, ev.text]);
      });
      const ok = code === 0;
      setSuccess(ok);
      setDone(true);
      onDone?.(ok);
    } catch (e: any) {
      setLines((l) => [...l, `Error: ${e.message}`]);
      setDone(true);
      setSuccess(false);
      onDone?.(false);
    } finally {
      setRunning(false);
    }
  }

  return (
    <Stack gap="md">
      <Group>
        <Button
          leftSection={<IconPlayerPlay size={15} />}
          color="orange"
          onClick={run}
          loading={running}
          disabled={done && success}
        >
          {done && success ? 'Done' : running ? `Running ${label}…` : `Run ${label}`}
        </Button>
        {done && !success && (
          <Button variant="subtle" color="red" onClick={run}>Retry</Button>
        )}
      </Group>
      {(running || done) && (
        <TerminalOutput lines={lines} done={done} success={success} />
      )}
    </Stack>
  );
}

// ── LLM Handoff step ───────────────────────────────────────────────────────────

function LLMHandoff({ onDone }: { onDone: (ok: boolean) => void }) {
  const [target, setTarget] = useState<number | string>(30);
  const [prefs, setPrefs] = useState('');
  const [prompt, setPrompt] = useState('');
  const [csvInfo, setCsvInfo] = useState<any>(null);
  const [pasteText, setPasteText] = useState('');
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; count?: number; error?: string } | null>(null);

  const PREFS_MAX = 200;
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
    if (r.ok) onDone(true);
  }

  async function handleFileDrop(files: File[]) {
    setValidating(true);
    const r = await api.validateFile(files[0]);
    setResult(r);
    setValidating(false);
    if (r.ok) onDone(true);
  }

  return (
    <Stack gap="lg">
      {/* Inputs row */}
      <Group grow align="flex-end">
        <NumberInput
          label="Target channel count"
          placeholder="e.g. 30"
          value={target}
          onChange={setTarget}
          onBlur={loadPrompt}
          min={1}
          max={500}
          step={1}
          size="sm"
        />
        <TextInput
          label="Theme preferences (optional)"
          placeholder="e.g. Batman, 90s cartoons, Documentaries"
          value={prefs}
          onChange={(e) => setPrefs(e.currentTarget.value)}
          onBlur={loadPrompt}
          maxLength={PREFS_MAX}
          rightSection={
            <Text size="xs" c={charsLeft < 20 ? 'red.4' : 'dimmed'} fw={500} style={{ userSelect: 'none' }}>
              {charsLeft}
            </Text>
          }
          rightSectionWidth={40}
          size="sm"
        />
      </Group>

      {/* Prompt + CSV side by side */}
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        {/* Prompt card */}
        <Card p="md">
          <Group justify="space-between" mb="sm">
            <Text fw={700}>Prompt</Text>
            <Button
              size="xs"
              variant="light"
              color="orange"
              leftSection={<IconCopy size={13} />}
              onClick={copyPrompt}
              disabled={!prompt}
            >
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

        {/* CSV card */}
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
              <Button
                component="a"
                href="/api/pipeline/csv"
                download="plex_library.csv"
                leftSection={<IconDownload size={15} />}
                color="orange"
                variant="light"
                size="sm"
                style={{ alignSelf: 'flex-start' }}
              >
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

      {/* Result panel — full width */}
      <Card p="md">
        <Text fw={700} mb="sm">LLM Result</Text>
        <Text size="sm" c="dimmed" mb="md">
          Paste the LLM output below, or drag and drop the file.
        </Text>

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

          {result && (
            <Alert
              color={result.ok ? 'green' : 'red'}
              icon={result.ok ? <IconCheck size={16} /> : <IconX size={16} />}
              variant="light"
            >
              {result.ok
                ? `Valid — ${result.count} channels loaded and saved to channels.json`
                : `Invalid — ${result.error}`}
            </Alert>
          )}

          {pasteText && !result && (
            <Button color="orange" onClick={validatePaste} loading={validating} style={{ alignSelf: 'flex-start' }}>
              Validate &amp; Save
            </Button>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}

// ── Collections config step ────────────────────────────────────────────────────

function CollectionsStep({ onDone }: { onDone: (ok: boolean) => void }) {
  const [base, setBase] = useState(80);
  const [minItems, setMinItems] = useState(3);
  const [condense, setCondense] = useState(false);
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [success, setSuccess] = useState(false);

  async function run() {
    setLines([]);
    setDone(false);
    setRunning(true);
    const code = await streamPipeline(
      '/pipeline/collections',
      { base: String(base), min_items: String(minItems), condense: String(condense) },
      (ev) => { if (ev.type === 'line') setLines((l) => [...l, ev.text]); },
    );
    const ok = code === 0;
    setSuccess(ok);
    setDone(true);
    setRunning(false);
    onDone(ok);
  }

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Optionally append Plex collections as channels. Collections are fetched live from Plex.
      </Text>
      <Group grow align="flex-end">
        <NumberInput
          label="Start collection channels at"
          value={base}
          onChange={(v) => setBase(Number(v))}
          min={1} max={999} size="sm"
        />
        <NumberInput
          label="Skip collections with fewer than N items"
          value={minItems}
          onChange={(v) => setMinItems(Number(v))}
          min={1} max={50} size="sm"
        />
      </Group>
      <Switch
        label="Skip collections that match an existing channel name"
        checked={condense}
        onChange={(e) => setCondense(e.currentTarget.checked)}
      />
      <Group>
        <Button color="orange" onClick={run} loading={running} leftSection={<IconPlayerPlay size={15} />}>
          {running ? 'Fetching…' : 'Fetch Collections'}
        </Button>
        <Button variant="subtle" color="gray" onClick={() => onDone(true)}>
          Skip Collections
        </Button>
      </Group>
      {(running || done) && <TerminalOutput lines={lines} done={done} success={success} />}
    </Stack>
  );
}

// ── Deploy step ────────────────────────────────────────────────────────────────

function DeployStep() {
  const [probeLines, setProbeLines] = useState<string[]>([]);
  const [probeDone, setProbeDone] = useState(false);
  const [probeOk, setProbeOk] = useState(false);
  const [probing, setProbing] = useState(false);

  const [deployLines, setDeployLines] = useState<string[]>([]);
  const [deployDone, setDeployDone] = useState(false);
  const [deployOk, setDeployOk] = useState(false);
  const [deploying, setDeploying] = useState(false);

  async function runProbe() {
    setProbeLines([]);
    setProbeDone(false);
    setProbing(true);
    const code = await streamPipeline('/pipeline/probe', {}, (ev) => {
      if (ev.type === 'line') setProbeLines((l) => [...l, ev.text]);
    });
    setProbeOk(code === 0);
    setProbeDone(true);
    setProbing(false);
  }

  async function runDeploy() {
    setDeployLines([]);
    setDeployDone(false);
    setDeploying(true);
    const code = await streamPipeline('/pipeline/deploy', {}, (ev) => {
      if (ev.type === 'line') setDeployLines((l) => [...l, ev.text]);
    });
    setDeployOk(code === 0);
    setDeployDone(true);
    setDeploying(false);
  }

  return (
    <Stack gap="lg">
      {/* Probe */}
      <Box>
        <Text fw={600} mb="sm">Step 1 — Probe (dry run)</Text>
        <Group mb="sm">
          <Button
            color="gray" variant="light"
            leftSection={<IconPlayerPlay size={15} />}
            onClick={runProbe} loading={probing}
          >
            {probing ? 'Running probe…' : 'Run Probe'}
          </Button>
        </Group>
        {(probing || probeDone) && <TerminalOutput lines={probeLines} done={probeDone} success={probeOk} />}
      </Box>

      <Divider />

      {/* Deploy */}
      <Box>
        <Text fw={600} mb="sm">Step 2 — Deploy</Text>
        {!probeDone && (
          <Alert color="gray" variant="light" icon={<IconAlertCircle size={16} />}>
            Run the probe first to verify channels before deploying.
          </Alert>
        )}
        {probeDone && !probeOk && (
          <Alert color="red" variant="light" icon={<IconX size={16} />}>
            Probe reported errors — fix them before deploying.
          </Alert>
        )}
        {probeDone && probeOk && (
          <Group mb="sm">
            <Button
              color="orange"
              leftSection={<IconPlayerPlay size={15} />}
              onClick={runDeploy}
              loading={deploying}
              disabled={deployDone && deployOk}
            >
              {deploying ? 'Deploying…' : deployDone && deployOk ? 'Deployed' : 'Deploy to Tunarr'}
            </Button>
          </Group>
        )}
        {(deploying || deployDone) && <TerminalOutput lines={deployLines} done={deployDone} success={deployOk} />}

        {deployDone && deployOk && (
          <Alert color="green" icon={<IconCheck size={16} />} mt="md" variant="light">
            Channels deployed! Use the Sync step or visit Plex Settings → Live TV &amp; DVR to refresh.
          </Alert>
        )}
      </Box>
    </Stack>
  );
}

// ── AI Path ────────────────────────────────────────────────────────────────────

function AIPath() {
  const [step, setStep] = useState(0);

  return (
    <Stepper active={step} onStepClick={setStep} color="orange" mt="md">
      <Stepper.Step label="Export" description="Fetch Plex library">
        <Box mt="lg">
          <RunStep label="Export" endpoint="/pipeline/export" onDone={(ok) => ok && setStep(1)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="LLM Handoff" description="Copy prompt, paste result">
        <Box mt="lg">
          <LLMHandoff onDone={(ok) => ok && setStep(2)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Collections" description="Optional Plex collections">
        <Box mt="lg">
          <CollectionsStep onDone={(ok) => ok && setStep(3)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Deploy" description="Probe & push">
        <Box mt="lg">
          <DeployStep />
        </Box>
      </Stepper.Step>

      <Stepper.Completed>
        <Alert color="green" icon={<IconCheck size={16} />} mt="lg">
          Pipeline complete. Head to the Dashboard to see your channels.
        </Alert>
      </Stepper.Completed>
    </Stepper>
  );
}

// ── No-AI Path ─────────────────────────────────────────────────────────────────

function NoAIPath() {
  const [step, setStep] = useState(0);

  return (
    <Stepper active={step} onStepClick={setStep} color="orange" mt="md">
      <Stepper.Step label="Export" description="Fetch Plex library">
        <Box mt="lg">
          <RunStep label="Export" endpoint="/pipeline/export" onDone={(ok) => ok && setStep(1)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Generate" description="Auto-build channels from metadata">
        <Box mt="lg">
          <Text size="sm" c="dimmed" mb="md">
            Automatically generates decade channels, genre channels, and TV marathon channels from your library metadata.
          </Text>
          <RunStep label="Generate" endpoint="/pipeline/no-ai" onDone={(ok) => ok && setStep(2)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Collections" description="Optional Plex collections">
        <Box mt="lg">
          <CollectionsStep onDone={(ok) => ok && setStep(3)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Deploy" description="Probe and push to Tunarr">
        <Box mt="lg">
          <DeployStep />
        </Box>
      </Stepper.Step>

      <Stepper.Completed>
        <Alert color="green" icon={<IconCheck size={16} />} mt="lg">
          Pipeline complete. Head to the Dashboard to see your channels.
        </Alert>
      </Stepper.Completed>
    </Stepper>
  );
}

// ── Collections-only Path ──────────────────────────────────────────────────────

function CollectionsPath() {
  const [step, setStep] = useState(0);

  return (
    <Stepper active={step} onStepClick={setStep} color="orange" mt="md">
      <Stepper.Step label="Generate" description="Fetch and build collection channels">
        <Box mt="lg">
          <CollectionsStep onDone={(ok) => ok && setStep(1)} />
        </Box>
      </Stepper.Step>

      <Stepper.Step label="Deploy" description="Probe and push to Tunarr">
        <Box mt="lg">
          <DeployStep />
        </Box>
      </Stepper.Step>

      <Stepper.Completed>
        <Alert color="green" icon={<IconCheck size={16} />} mt="lg">
          Collections deployed.
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
