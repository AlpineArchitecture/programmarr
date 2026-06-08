import {
  ActionIcon, Badge, Box, Button, Card, Checkbox, Divider, Group,
  Loader, Modal, ScrollArea, Select, Stack, Switch, Text, TextInput, Title,
  Tooltip,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import {
  IconCheck, IconEdit, IconPlus, IconRepeat, IconTag, IconTrash, IconX,
} from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api, Channel, ChannelSyncState, ContentItem, FillerList, isMatchRef, RecipeMatch, TunarrChannel } from '../api/client';

function syncedAgo(iso?: string): string {
  if (!iso) return 'never';
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 90) return 'just now';
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

const SHUFFLE_COLOR: Record<string, string> = { ordered: 'blue', block: 'violet', shuffle: 'teal' };
const SHUFFLE_OPTIONS = [
  { value: 'shuffle',  label: 'Shuffle — random order' },
  { value: 'ordered',  label: 'Ordered — sequential' },
  { value: 'block',    label: 'Block — grouped by show' },
];

interface MatchRule { value: string; order: string; exclude: string[] }

// ── Franchise auto-match builder ───────────────────────────────────────────────

function FranchiseBuilder({
  initial,
  onSave,
  onCancel,
}: {
  initial: MatchRule | null;
  onSave: (rule: MatchRule) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial?.value ?? '');
  const [order, setOrder] = useState(initial?.order ?? 'release_date');
  const [excluded, setExcluded] = useState<Set<string>>(new Set(initial?.exclude ?? []));
  const [matches, setMatches] = useState<RecipeMatch[] | null>(null);
  const [previewing, setPreviewing] = useState(false);

  async function preview() {
    if (!value.trim()) return;
    setPreviewing(true);
    try {
      const res = await api.previewRecipe(value.trim(), order, []); // full candidate list
      setMatches(res.matches);
    } catch (e: any) {
      notifications.show({ title: 'Preview failed', message: e.message, color: 'red' });
    } finally {
      setPreviewing(false);
    }
  }

  // Auto-preview when editing an existing rule so the checklist is populated
  useEffect(() => { if (initial?.value) preview(); /* eslint-disable-next-line */ }, []);

  function toggle(title: string) {
    setExcluded((s) => {
      const n = new Set(s);
      if (n.has(title)) n.delete(title); else n.add(title);
      return n;
    });
  }

  const includedCount = matches ? matches.filter((m) => !excluded.has(m.title)).length : 0;

  return (
    <Card withBorder p="sm" bg="dark.6">
      <Stack gap="xs">
        <Text size="sm" fw={600}>Franchise auto-match</Text>
        <Text size="xs" c="dimmed">
          Auto-add every library title containing this phrase (whole-word match — "It" matches
          "It Follows", not "Little Women"). New matching films join the channel automatically.
        </Text>

        <Group gap="xs" align="end">
          <TextInput
            label="Title contains"
            placeholder="e.g. Bad Boys"
            value={value}
            onChange={(e) => setValue(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && preview()}
            style={{ flex: 1 }}
            size="xs"
          />
          <Select
            label="Order"
            size="xs"
            w={140}
            data={[
              { value: 'release_date', label: 'Release date' },
              { value: 'alpha', label: 'Alphabetical' },
            ]}
            value={order}
            onChange={(v) => setOrder(v || 'release_date')}
            allowDeselect={false}
          />
          <Button size="xs" variant="light" color="orange" onClick={preview} loading={previewing}>
            Preview
          </Button>
        </Group>

        {matches && (
          <>
            <Text size="xs" c="dimmed">
              {includedCount} of {matches.length} included
              {excluded.size ? ` · ${excluded.size} excluded` : ''}
            </Text>
            {matches.length === 0 ? (
              <Text size="xs" c="yellow.4">No titles match — try a different phrase.</Text>
            ) : (
              <ScrollArea.Autosize mah={180}>
                <Stack gap={2}>
                  {matches.map((m) => (
                    <Checkbox
                      key={m.title}
                      size="xs"
                      color="orange"
                      checked={!excluded.has(m.title)}
                      onChange={() => toggle(m.title)}
                      label={
                        <Text size="xs">
                          {m.title}
                          {m.year ? <Text span c="dimmed"> ({m.year})</Text> : null}
                        </Text>
                      }
                    />
                  ))}
                </Stack>
              </ScrollArea.Autosize>
            )}
          </>
        )}

        <Group justify="flex-end" gap="xs">
          <Button size="xs" variant="subtle" color="gray" onClick={onCancel}>Cancel</Button>
          <Button
            size="xs"
            color="orange"
            disabled={!value.trim()}
            onClick={() => onSave({ value: value.trim(), order, exclude: Array.from(excluded) })}
          >
            Save rule
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}

// ── Channel editor modal ───────────────────────────────────────────────────────

function ChannelModal({
  channel,
  opened,
  onClose,
  onSaved,
}: {
  channel: Channel | null;
  opened: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState('');
  const [number, setNumber] = useState('');
  const [shuffle, setShuffle] = useState<string>('shuffle');
  const [content, setContent] = useState<string[]>([]);
  const [newItem, setNewItem] = useState('');
  const [live, setLive] = useState(false);
  const [matchRef, setMatchRef] = useState<MatchRule | null>(null);
  const [building, setBuilding] = useState(false);
  const [saving, setSaving] = useState(false);

  // Commercials
  const [commEnabled, setCommEnabled] = useState(false);
  const [commListId, setCommListId] = useState<string | null>(null);
  const [commPad, setCommPad] = useState('5');
  const [fillerLists, setFillerLists] = useState<FillerList[]>([]);

  // Filler lists live in Tunarr; fetch once so the picker can offer them.
  useEffect(() => {
    api.getFillerLists().then(setFillerLists).catch(() => setFillerLists([]));
  }, []);

  useEffect(() => {
    if (!channel) return;
    setName(channel.name);
    setNumber(String(channel.number));
    setShuffle(channel.shuffle || 'shuffle');
    setLive(!!channel.live);
    setBuilding(false);
    const comm = channel.commercials;
    setCommEnabled(!!comm?.filler_list_id);
    setCommListId(comm?.filler_list_id ?? null);
    setCommPad(String(comm?.pad_minutes ?? 5));

    const mref = channel.content.find(isMatchRef);
    setMatchRef(mref ? { value: mref.value, order: mref.order || 'release_date', exclude: mref.exclude || [] } : null);
    setContent(
      channel.content
        .filter((c) => !isMatchRef(c))
        .map((c) => (typeof c === 'string' ? c : `{collection: ${(c as any).collection}}`))
    );
  }, [channel]);

  function addItem() {
    if (!newItem.trim()) return;
    setContent((c) => [...c, newItem.trim()]);
    setNewItem('');
  }

  function removeItem(i: number) {
    setContent((c) => c.filter((_, idx) => idx !== i));
  }

  async function persist() {
    const rawContent: ContentItem[] = content.map((c) => {
      const m = c.match(/^\{collection:\s*(.+)\}$/);
      return m ? { collection: m[1] } : c;
    });
    if (matchRef) {
      rawContent.push({
        match: 'title_contains',
        value: matchRef.value,
        order: matchRef.order,
        exclude: matchRef.exclude,
      });
    }
    const payload: any = { number: Number(number), name, shuffle, content: rawContent };
    if (live) payload.live = true;
    if (commEnabled && commListId) {
      payload.commercials = {
        filler_list_id: commListId,
        filler_list_name: fillerLists.find((f) => f.id === commListId)?.name,
        pad_minutes: Number(commPad),
      };
    }
    await api.updateChannel(channel!.number, payload);
  }

  // Save to channels.json then immediately push to Tunarr in place.
  async function saveAndApply() {
    if (!channel) return;
    setSaving(true);
    try {
      await persist();
      await api.applyChannel(channel.number);
      notifications.show({ message: `Channel #${channel.number} saved and applied`, color: 'green', icon: <IconCheck size={14} /> });
      onSaved();
      onClose();
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={<Text fw={700}>Edit Channel #{channel?.number}</Text>}
      size="lg"
    >
      <Stack gap="sm">
        <Group grow>
          <TextInput
            label="Channel number"
            value={number}
            onChange={(e) => setNumber(e.currentTarget.value)}
          />
          <TextInput
            label="Name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
          />
        </Group>

        <Select
          label="Shuffle mode"
          data={SHUFFLE_OPTIONS}
          value={shuffle}
          onChange={(v) => setShuffle(v || 'shuffle')}
        />

        <Divider label="Content" labelPosition="left" />

        <Stack gap={4}>
          {content.map((item, i) => (
            <Group key={i} gap="xs" wrap="nowrap">
              <Text size="sm" style={{ flex: 1, fontFamily: 'ui-monospace, monospace' }} truncate>
                {item}
              </Text>
              <ActionIcon size="sm" color="red" variant="subtle" onClick={() => removeItem(i)}>
                <IconX size={14} />
              </ActionIcon>
            </Group>
          ))}
          {content.length === 0 && !matchRef && (
            <Text size="xs" c="dimmed">No fixed titles — add titles below or a franchise auto-match.</Text>
          )}
        </Stack>

        <Group gap="xs">
          <TextInput
            placeholder="Add title or {collection: Name}"
            value={newItem}
            onChange={(e) => setNewItem(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && addItem()}
            style={{ flex: 1 }}
            size="sm"
          />
          <Button size="sm" variant="light" color="orange" onClick={addItem} leftSection={<IconPlus size={14} />}>
            Add
          </Button>
        </Group>

        <Divider label="Live recipe" labelPosition="left" />

        <Switch
          checked={live}
          onChange={(e) => setLive(e.currentTarget.checked)}
          color="orange"
          label="Auto-update on a schedule"
          description="Re-resolves this channel against your library and patches it in place. New episodes and matching franchise films appear automatically — no redeploy."
        />

        {matchRef && !building ? (
          <Card withBorder p="xs">
            <Group justify="space-between" wrap="nowrap">
              <Box style={{ minWidth: 0 }}>
                <Group gap={6}>
                  <IconRepeat size={14} />
                  <Text size="sm" fw={600} truncate>“{matchRef.value}”</Text>
                </Group>
                <Text size="xs" c="dimmed">
                  {matchRef.order === 'release_date' ? 'release date order' : 'alphabetical'}
                  {matchRef.exclude.length ? ` · ${matchRef.exclude.length} excluded` : ''}
                </Text>
              </Box>
              <Group gap={4}>
                <ActionIcon variant="subtle" color="gray" onClick={() => setBuilding(true)}>
                  <IconEdit size={14} />
                </ActionIcon>
                <ActionIcon variant="subtle" color="red" onClick={() => setMatchRef(null)}>
                  <IconTrash size={14} />
                </ActionIcon>
              </Group>
            </Group>
          </Card>
        ) : building ? (
          <FranchiseBuilder
            initial={matchRef}
            onSave={(rule) => { setMatchRef(rule); setBuilding(false); }}
            onCancel={() => setBuilding(false)}
          />
        ) : (
          <Button
            size="xs"
            variant="light"
            color="orange"
            leftSection={<IconPlus size={14} />}
            onClick={() => setBuilding(true)}
            style={{ alignSelf: 'flex-start' }}
          >
            Add franchise auto-match
          </Button>
        )}

        <Divider label="Commercials" labelPosition="left" />

        <Switch
          checked={commEnabled}
          onChange={(e) => {
            const on = e.currentTarget.checked;
            setCommEnabled(on);
            if (on && !commListId && fillerLists.length) setCommListId(fillerLists[0].id);
          }}
          color="orange"
          label="Play commercials between shows"
          description="Pulls clips from a Tunarr filler list and plays them in a short gap after each show — like real TV."
        />

        {commEnabled && (
          fillerLists.length === 0 ? (
            <Text size="xs" c="yellow.4">
              No filler lists found in Tunarr. Create one in Tunarr first (a library of
              commercial / bumper clips), then reopen this editor.
            </Text>
          ) : (
            <Group grow align="start">
              <Select
                label="Filler list"
                data={fillerLists.map((f) => ({ value: f.id, label: `${f.name} (${f.contentCount})` }))}
                value={commListId}
                onChange={setCommListId}
                allowDeselect={false}
              />
              <Select
                label="Break length"
                data={[
                  { value: '5', label: 'Short (~3 min)' },
                  { value: '30', label: 'Long (~8 min)' },
                ]}
                value={commPad}
                onChange={(v) => setCommPad(v || '5')}
                allowDeselect={false}
              />
            </Group>
          )
        )}

        <Divider />

        <Group justify="flex-end">
          <Button variant="subtle" color="gray" onClick={onClose}>Cancel</Button>
          <Button color="orange" onClick={saveAndApply} loading={saving}>Save and Apply</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

// ── Channel row ────────────────────────────────────────────────────────────────

function ChannelRow({
  channel,
  sync,
  onEdit,
  onDelete,
}: {
  channel: TunarrChannel;
  sync?: ChannelSyncState;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [deleting, setDeleting] = useState(false);

  async function del() {
    if (!confirm(`Delete channel #${channel.number} "${channel.name}"?`)) return;
    setDeleting(true);
    try {
      await api.deleteChannel(channel.number);
      onDelete();
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' });
      setDeleting(false);
    }
  }

  return (
    <Card p="sm" mb="xs">
      <Group gap="sm" wrap="nowrap">
        <Badge
          size="lg"
          variant="filled"
          color="dark"
          radius="sm"
          style={{ minWidth: 52, fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}
        >
          {channel.number}
        </Badge>

        <Box style={{ flex: 1, minWidth: 0 }}>
          <Text size="sm" fw={600} truncate>{channel.name}</Text>
          {sync?.checked_at && (
            <Group gap={4} mt={2}>
              <Badge size="xs" color="orange" variant="light" leftSection={<IconRepeat size={10} />}>
                live
              </Badge>
              <Text size="xs" c="dimmed">synced {syncedAgo(sync.checked_at)}</Text>
            </Group>
          )}
        </Box>

        <Group gap={4} style={{ flexShrink: 0 }}>
          <Tooltip label="Edit">
            <ActionIcon variant="subtle" color="gray" onClick={onEdit}>
              <IconEdit size={16} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="Delete from channels.json">
            <ActionIcon variant="subtle" color="red" onClick={del} loading={deleting}>
              <IconTrash size={16} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>
    </Card>
  );
}

function OrphanRow({ channel }: { channel: TunarrChannel }) {
  return (
    <Card p="sm" mb="xs" style={{ opacity: 0.65 }}>
      <Group gap="sm" wrap="nowrap">
        <Badge
          size="lg"
          variant="filled"
          color="dark"
          radius="sm"
          style={{ minWidth: 52, fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}
        >
          {channel.number}
        </Badge>

        <Box style={{ flex: 1, minWidth: 0 }}>
          <Text size="sm" fw={600} truncate>{channel.name}</Text>
          <Badge size="xs" color="gray" variant="light" mt={2}>Not managed by Programmarr</Badge>
        </Box>
      </Group>
    </Card>
  );
}

// ── Root ───────────────────────────────────────────────────────────────────────

export default function Channels() {
  const { number } = useParams<{ number?: string }>();
  const nav = useNavigate();
  const [channels, setChannels] = useState<TunarrChannel[]>([]);
  const [managed, setManaged] = useState<Set<number>>(new Set());
  const [sync, setSync] = useState<Record<string, ChannelSyncState>>({});
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Channel | null>(null);
  const [opened, { open, close }] = useDisclosure(false);

  async function load() {
    const [tunarr, local] = await Promise.all([
      api.getTunarrChannels(),
      api.getChannels().catch(() => ({ channels: [], orphaned: [], suggested_channels: [] })),
    ]);
    setChannels([...tunarr].sort((a, b) => a.number - b.number));
    setManaged(new Set(local.channels.map((c) => c.number)));
    setLoading(false);
    api.getRecipesStatus().then((s) => setSync(s.channels || {})).catch(() => {});
  }

  useEffect(() => { load(); }, []);

  // Deep-link: open the channel named in the URL once the list has loaded.
  // The ref guard ensures a list reload (e.g. after Save) never re-opens a
  // modal the user just closed — fixing the "save bounces the window" bug.
  const openedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!number) { openedFor.current = null; return; }
    if (openedFor.current === number || channels.length === 0) return;
    const n = Number(number);
    if (!managed.has(n)) return; // orphan — don't open modal
    openedFor.current = number;
    api.getChannel(n)
      .then((ch) => { setEditing(ch); open(); })
      .catch(() => {}); // 404 = orphan after all; stay closed
  }, [number, channels, managed]);

  function edit(ch: TunarrChannel) {
    nav(`/channels/${ch.number}`, { replace: true });
    api.getChannel(ch.number)
      .then((full) => { setEditing(full); open(); })
      .catch(() => {});
  }

  function handleClose() {
    close();
    nav('/channels', { replace: true });
  }

  if (loading) {
    return <Stack align="center" justify="center" h={400}><Loader color="orange" /></Stack>;
  }

  const liveCount = Array.from(managed).filter((n) => {
    // live flag only known from channels.json — approximate from sync state
    return !!sync[String(n)];
  }).length;
  // Show live badge count from sync state as a proxy; exact count needs local data
  const syncedCount = Object.keys(sync).length;

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Title order={2}>Channels ({channels.length})</Title>
        {syncedCount > 0 && (
          <Badge color="orange" variant="light" leftSection={<IconRepeat size={12} />}>
            {syncedCount} live
          </Badge>
        )}
      </Group>

      {channels.length === 0 ? (
        <Card p="xl">
          <Stack align="center" gap="xs">
            <Text c="dimmed">No channels in Tunarr yet — run the pipeline first</Text>
          </Stack>
        </Card>
      ) : (
        <Box>
          {channels.map((ch) => (
            managed.has(ch.number) ? (
              <ChannelRow
                key={ch.number}
                channel={ch}
                sync={sync[String(ch.number)]}
                onEdit={() => edit(ch)}
                onDelete={() => load()}
              />
            ) : (
              <OrphanRow key={ch.number} channel={ch} />
            )
          ))}
        </Box>
      )}

      <ChannelModal
        channel={editing}
        opened={opened}
        onClose={handleClose}
        onSaved={load}
      />
    </Stack>
  );
}
