import {
  ActionIcon, Alert, Badge, Box, Button, Card, Group,
  Loader, SimpleGrid, Stack, Text, ThemeIcon, Title, Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconBolt, IconBroadcast, IconCircleCheck, IconCircleX,
  IconPlayerPause, IconPlayerPlay, IconRefresh, IconRepeat, IconSettings,
} from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ConnStatus, RecipesStatus, TunarrChannel } from '../api/client';

function ConnectionCard({ label, status }: { label: string; status: ConnStatus | undefined }) {
  const ok = status?.ok ?? false;
  return (
    <Card p="sm">
      <Group gap="sm">
        <ThemeIcon size="md" radius="xl" color={ok ? 'green' : 'red'} variant="light">
          {ok ? <IconCircleCheck size={16} /> : <IconCircleX size={16} />}
        </ThemeIcon>
        <Box style={{ flex: 1, minWidth: 0 }}>
          <Text size="sm" fw={600}>{label}</Text>
          <Text size="xs" c="dimmed" truncate style={{ maxWidth: 180 }}>
            {status?.url || 'Not configured'}
          </Text>
          {!ok && status?.error && (
            <Text size="xs" c="red.4" truncate>{status.error}</Text>
          )}
        </Box>
        <Badge color={ok ? 'green' : 'red'} variant="dot">{ok ? 'Online' : 'Offline'}</Badge>
      </Group>
    </Card>
  );
}

const SHUFFLE_COLOR: Record<string, string> = { ordered: 'blue', block: 'violet', shuffle: 'teal' };

function ChannelCard({ ch, onClick }: { ch: TunarrChannel; onClick: () => void }) {
  return (
    <Card
      p="sm"
      style={{ cursor: 'pointer', transition: 'border-color 120ms' }}
      onClick={onClick}
      styles={{ root: { '&:hover': { borderColor: 'var(--mantine-color-orange-5)' } } }}
    >
      <Group gap="sm" wrap="nowrap">
        <Badge
          size="lg"
          variant="filled"
          color="dark"
          radius="sm"
          style={{ minWidth: 48, fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}
        >
          {ch.number}
        </Badge>
        <Text size="sm" fw={600} truncate style={{ flex: 1 }}>{ch.name}</Text>
      </Group>
    </Card>
  );
}

function relTime(iso: string): string {
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 90) return 'just now';
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

function inTime(secs: number): string {
  if (secs < 90) return 'in <1m';
  if (secs < 3600) return `in ${Math.round(secs / 60)}m`;
  if (secs < 86400) return `in ${Math.round(secs / 3600)}h`;
  return `in ${Math.round(secs / 86400)}d`;
}

function LiveRecipesCard({ status, onChange }: { status: RecipesStatus; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const last = status.last_cycle;

  async function runNow() {
    setBusy(true);
    try {
      const res = await api.runRecipes(true);
      notifications.show({
        title: 'Live channels checked',
        message: res.changed > 0 ? `${res.changed} channel(s) updated` : 'Everything already up to date',
        color: res.changed > 0 ? 'orange' : 'green',
      });
      onChange();
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' });
    } finally {
      setBusy(false);
    }
  }

  async function togglePause() {
    setBusy(true);
    try {
      await api.pauseRecipes(!status.paused);
      onChange();
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card p="md">
      <Group justify="space-between" mb="sm" wrap="nowrap">
        <Group gap="sm">
          <ThemeIcon size="md" radius="xl" variant="light" color={status.paused ? 'yellow' : 'orange'}>
            <IconRepeat size={16} />
          </ThemeIcon>
          <Box>
            <Group gap={6}>
              <Text size="sm" fw={600}>Auto-Updates</Text>
              {status.paused
                ? <Badge size="xs" color="yellow" variant="light">Paused</Badge>
                : <Badge size="xs" color="orange" variant="dot">On</Badge>}
            </Group>
            <Text size="xs" c="dimmed">
              {status.live_count} live channel{status.live_count !== 1 ? 's' : ''} · every {status.interval_hours}h
              {status.next_run_seconds != null && !status.paused ? ` · next ${inTime(status.next_run_seconds)}` : ''}
            </Text>
          </Box>
        </Group>
        <Group gap={4} wrap="nowrap">
          <Tooltip label={status.paused ? 'Resume' : 'Pause auto-updates'}>
            <ActionIcon variant="light" color={status.paused ? 'orange' : 'gray'} onClick={togglePause} loading={busy}>
              {status.paused ? <IconPlayerPlay size={16} /> : <IconPlayerPause size={16} />}
            </ActionIcon>
          </Tooltip>
          <Button size="compact-sm" variant="light" color="orange" leftSection={<IconBolt size={14} />} onClick={runNow} loading={busy}>
            Check now
          </Button>
        </Group>
      </Group>

      {last && (
        <Box>
          <Text size="xs" c="dimmed">
            Last check {relTime(last.time)}
            {last.error ? ' · error' : last.changed > 0 ? ` · ${last.changed} updated` : ' · no changes'}
          </Text>
          {last.error && <Text size="xs" c="red.4">{last.error}</Text>}
          {last.changes.slice(0, 4).map((c) => (
            <Text key={c.number} size="xs" mt={2}>
              <Text span fw={600}>#{c.number} {c.name}</Text>
              <Text span c="dimmed">
                {' '}+{c.added_count}{c.removed_count ? ` −${c.removed_count}` : ''}
                {c.added.length ? `: ${c.added.slice(0, 3).join(', ')}` : ''}
              </Text>
            </Text>
          ))}
        </Box>
      )}
    </Card>
  );
}

export default function Dashboard() {
  const nav = useNavigate();
  const [status, setStatus] = useState<{ tunarr: ConnStatus; plex: ConnStatus } | null>(null);
  const [channels, setChannels] = useState<TunarrChannel[]>([]);
  const [recipes, setRecipes] = useState<RecipesStatus | null>(null);
  const [configured, setConfigured] = useState(true);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  async function load(silent = false) {
    silent ? setRefreshing(true) : setLoading(true);
    try {
      const [s, ch, cs, rs] = await Promise.all([
        api.getStatus(),
        api.getTunarrChannels(),
        api.getConfigStatus(),
        api.getRecipesStatus().catch(() => null),
      ]);
      setStatus(s);
      setChannels([...ch].sort((a, b) => a.number - b.number));
      setConfigured(cs.configured);
      setRecipes(rs);
    } catch { /* ignore */ }
    finally { setLoading(false); setRefreshing(false); }
  }

  async function reloadRecipes() {
    try { setRecipes(await api.getRecipesStatus()); } catch { /* ignore */ }
  }

  useEffect(() => { load(); }, []);

  if (loading) {
    return <Stack align="center" justify="center" h={400}><Loader color="orange" /></Stack>;
  }

  return (
    <Stack gap="xl">
      <Group justify="space-between">
        <Title order={2}>Dashboard</Title>
        <ActionIcon variant="subtle" onClick={() => load(true)} loading={refreshing} color="gray">
          <IconRefresh size={18} />
        </ActionIcon>
      </Group>

      {!configured && (
        <Alert
          color="orange"
          variant="light"
          icon={<IconSettings size={18} />}
          title="Setup required"
        >
          Tunarr URL, Plex URL, and Plex Token aren't configured yet.{' '}
          <Button
            variant="subtle"
            color="orange"
            size="compact-sm"
            onClick={() => nav('/settings')}
            style={{ verticalAlign: 'baseline' }}
          >
            Go to Settings →
          </Button>
        </Alert>
      )}

      {/* Connections */}
      <Box>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb="xs" style={{ letterSpacing: '0.08em' }}>
          Connections
        </Text>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <ConnectionCard label="Tunarr" status={status?.tunarr} />
          <ConnectionCard label="Plex"   status={status?.plex} />
        </SimpleGrid>
      </Box>

      {/* Auto-updates (live channels) — only when enabled or some channels are live */}
      {recipes && (recipes.enabled || recipes.live_count > 0) && (
        <Box>
          <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb="xs" style={{ letterSpacing: '0.08em' }}>
            Auto-Updates
          </Text>
          <LiveRecipesCard status={recipes} onChange={reloadRecipes} />
        </Box>
      )}

      {/* Channel grid */}
      <Box>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb="xs" style={{ letterSpacing: '0.08em' }}>
          Live Channels ({channels.length})
        </Text>

        {channels.length === 0 ? (
          <Card p="xl">
            <Stack align="center" gap="md">
              <ThemeIcon size={52} variant="light" color="orange" radius="xl">
                <IconBroadcast size={30} />
              </ThemeIcon>
              <Stack align="center" gap={4}>
                <Text fw={600}>No channels in Tunarr yet</Text>
                <Text size="sm" c="dimmed">Run the pipeline to build your first channels</Text>
              </Stack>
              <Button leftSection={<IconPlayerPlay size={16} />} color="orange" onClick={() => nav('/run')}>
                Run Pipeline
              </Button>
            </Stack>
          </Card>
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 4 }}>
            {channels.map((ch) => (
              <ChannelCard key={ch.number} ch={ch} onClick={() => nav(`/channels/${ch.number}`)} />
            ))}
          </SimpleGrid>
        )}
      </Box>
    </Stack>
  );
}
