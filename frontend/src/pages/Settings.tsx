import {
  ActionIcon, Alert, Box, Button, Card, Divider, Group,
  NumberInput, PasswordInput, Stack, Switch, Text, TextInput, Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconAlertCircle, IconArrowDown, IconArrowUp, IconCheck,
  IconDeviceFloppy, IconRepeat,
} from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { api } from '../api/client';

const MASK = '••••••••';

// Mirrors channel_blocks.py CANONICAL_ORDER + BLOCK_LABELS.
const CANONICAL_ORDER = [
  'marathon', 'tv_block', 'tv_movie_mix', 'movie', 'entity',
  'network', 'programming_block', 'franchise', 'specialty',
];
const BLOCK_LABELS: Record<string, string> = {
  marathon:          'TV Marathons',
  tv_block:          'TV Blocks',
  tv_movie_mix:      'TV & Movie Mix',
  movie:             'Movie Channels',
  entity:            'Studios / Directors / Actors',
  network:           'Networks',
  programming_block: 'Classic TV Blocks',
  franchise:         'Franchise & Series',
  specialty:         'Specialty',
};

/** Resolve a stored order against the canonical list — same logic as channel_blocks.resolve_order. */
function resolveOrder(stored: string[]): string[] {
  const known = new Set(CANONICAL_ORDER);
  const filtered = stored.filter((k) => known.has(k));
  const present = new Set(filtered);
  const tail = CANONICAL_ORDER.filter((k) => !present.has(k));
  return [...filtered, ...tail];
}

interface CategoryOrderEditorProps {
  order: string[];
  onChange: (order: string[]) => void;
}

function CategoryOrderEditor({ order, onChange }: CategoryOrderEditorProps) {
  function move(index: number, direction: -1 | 1) {
    const next = [...order];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <Stack gap={4}>
      {order.map((key, i) => (
        <Group key={key} gap="xs" wrap="nowrap">
          <ActionIcon
            variant="subtle"
            size="sm"
            disabled={i === 0}
            onClick={() => move(i, -1)}
            aria-label="Move up"
          >
            <IconArrowUp size={14} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            size="sm"
            disabled={i === order.length - 1}
            onClick={() => move(i, 1)}
            aria-label="Move down"
          >
            <IconArrowDown size={14} />
          </ActionIcon>
          <Text size="sm" style={{ flex: 1 }}>
            {BLOCK_LABELS[key] ?? key}
          </Text>
        </Group>
      ))}
    </Stack>
  );
}

export default function Settings() {
  const [values, setValues] = useState({
    tunarr_url: '', plex_url: '', plex_token: '',
    tmdb_api_key: '', auth_username: '', auth_password: '',
  });
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const [recipesEnabled, setRecipesEnabled] = useState(false);
  const [recipeInterval, setRecipeInterval] = useState(12);
  const [savingRecipes, setSavingRecipes] = useState(false);

  const [channelOrder, setChannelOrder] = useState<string[]>(CANONICAL_ORDER);

  useEffect(() => {
    api.getConfig().then((cfg) => {
      setValues({
        tunarr_url:    cfg.tunarr_url    || '',
        plex_url:      cfg.plex_url      || '',
        plex_token:    cfg.plex_token    || '',
        tmdb_api_key:  cfg.tmdb_api_key  || '',
        auth_username: cfg.auth_username || '',
        auth_password: cfg.auth_password || '',
      });
      const stored: string[] = cfg.channel_order || [];
      setChannelOrder(resolveOrder(stored));
      setLoaded(true);
    });
    api.getRecipesStatus().then((s) => {
      setRecipesEnabled(s.enabled);
      setRecipeInterval(s.interval_hours);
    }).catch(() => {});
  }, []);

  async function saveRecipes() {
    setSavingRecipes(true);
    try {
      await api.saveRecipeConfig(recipesEnabled, recipeInterval);
      notifications.show({
        title: 'Saved',
        message: `Auto-updates ${recipesEnabled ? 'enabled' : 'disabled'}`,
        color: 'green',
        icon: <IconCheck size={16} />,
      });
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' });
    } finally {
      setSavingRecipes(false);
    }
  }

  function set(key: string, val: string) {
    setValues((v) => ({ ...v, [key]: val }));
  }

  async function save() {
    setSaving(true);
    try {
      await api.saveConfig({ ...values, channel_order: channelOrder });
      notifications.show({
        title: 'Saved',
        message: 'Configuration updated',
        color: 'green',
        icon: <IconCheck size={16} />,
      });
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' });
    } finally {
      setSaving(false);
    }
  }

  const isMasked = (v: string) => v === MASK;

  return (
    <Stack gap="xl" maw={640}>
      <Title order={2}>Settings</Title>

      {/* Connections */}
      <Card p="lg">
        <Text fw={700} mb="md">Connections</Text>

        <Stack gap="sm">
          <TextInput
            label="Tunarr URL"
            placeholder="http://192.168.1.10:8000"
            value={values.tunarr_url}
            onChange={(e) => set('tunarr_url', e.currentTarget.value)}
          />
          <TextInput
            label="Plex URL"
            placeholder="http://192.168.1.10:32400"
            value={values.plex_url}
            onChange={(e) => set('plex_url', e.currentTarget.value)}
          />
          <PasswordInput
            label="Plex Token"
            placeholder={isMasked(values.plex_token) ? 'Token saved — enter new value to change' : 'Your Plex token'}
            value={isMasked(values.plex_token) ? '' : values.plex_token}
            onChange={(e) => set('plex_token', e.currentTarget.value || MASK)}
          />
        </Stack>
      </Card>

      {/* TMDB */}
      <Card p="lg">
        <Text fw={700} mb={4}>TMDB API Key</Text>
        <Text size="xs" c="dimmed" mb="md">Optional — required for channel logo images only</Text>
        <PasswordInput
          placeholder={isMasked(values.tmdb_api_key) ? 'Key saved — enter new value to change' : 'Get a free key at themoviedb.org'}
          value={isMasked(values.tmdb_api_key) ? '' : values.tmdb_api_key}
          onChange={(e) => set('tmdb_api_key', e.currentTarget.value || MASK)}
        />
      </Card>

      {/* Auth */}
      <Card p="lg">
        <Text fw={700} mb={4}>Authentication</Text>
        <Text size="xs" c="dimmed" mb="md">
          Optional — enables HTTP Basic Auth on the whole UI. Leave blank to disable.
        </Text>
        <Stack gap="sm">
          <TextInput
            label="Username"
            placeholder="admin"
            value={values.auth_username}
            onChange={(e) => set('auth_username', e.currentTarget.value)}
          />
          <PasswordInput
            label="Password"
            placeholder={isMasked(values.auth_password) ? 'Password saved — enter new value to change' : 'Set a password'}
            value={isMasked(values.auth_password) ? '' : values.auth_password}
            onChange={(e) => set('auth_password', e.currentTarget.value || MASK)}
          />
        </Stack>

        {values.auth_username && (
          <Alert icon={<IconAlertCircle size={16} />} color="yellow" mt="md" variant="light">
            After saving, you'll need to reload the page and enter these credentials.
          </Alert>
        )}
      </Card>

      {/* Channel ordering */}
      <Card p="lg">
        <Text fw={700} mb={4}>Channel Numbering</Text>
        <Text size="xs" c="dimmed" mb="md">
          Channels are numbered 1, 2, 3… in this category order. Empty categories consume
          no numbers — if you have 15 marathons they get 1–15, then the next category
          starts at 16.
        </Text>
        <CategoryOrderEditor order={channelOrder} onChange={setChannelOrder} />
      </Card>

      <Group>
        <Button
          leftSection={<IconDeviceFloppy size={16} />}
          color="orange"
          onClick={save}
          loading={saving}
          disabled={!loaded}
        >
          Save Changes
        </Button>
      </Group>

      {/* Live channels (auto-update) */}
      <Card p="lg">
        <Group gap={6} mb={4}>
          <IconRepeat size={16} />
          <Text fw={700}>Live Channels</Text>
        </Group>
        <Text size="xs" c="dimmed" mb="md">
          When enabled, channels marked "live" are re-checked on a schedule and patched in place as
          your library grows (new episodes, new franchise films) — no redeploy. Off by default.
        </Text>
        <Stack gap="sm">
          <Switch
            checked={recipesEnabled}
            onChange={(e) => setRecipesEnabled(e.currentTarget.checked)}
            color="orange"
            label="Enable automatic updates"
          />
          <NumberInput
            label="Check interval (hours)"
            description="How often the scheduler re-checks live channels"
            value={recipeInterval}
            onChange={(v) => setRecipeInterval(Number(v) || 12)}
            min={1}
            max={168}
            w={220}
            disabled={!recipesEnabled}
          />
          <Group>
            <Button
              leftSection={<IconDeviceFloppy size={16} />}
              color="orange"
              variant="light"
              onClick={saveRecipes}
              loading={savingRecipes}
            >
              Save Live Settings
            </Button>
          </Group>
        </Stack>
      </Card>
    </Stack>
  );
}
