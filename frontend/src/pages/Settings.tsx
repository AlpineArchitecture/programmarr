import {
  Alert, Box, Button, Card, Code, Divider, Group, NumberInput,
  PasswordInput, SimpleGrid, Stack, Switch, Text, TextInput, Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAlertCircle, IconCheck, IconDeviceFloppy, IconRepeat } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { api } from '../api/client';

const MASK = '••••••••';

// Mirrors channel_blocks.py (CANONICAL_ORDER, DEFAULT_SIZES). Keep in sync.
const BLOCKS: { key: string; label: string }[] = [
  { key: 'marathon', label: 'TV Marathons' },
  { key: 'tv_block', label: 'TV Blocks' },
  { key: 'movie', label: 'Movie Channels' },
  { key: 'franchise', label: 'Franchise & Series' },
  { key: 'specialty', label: 'Specialty' },
];
const BLOCK_DEFAULTS: Record<string, number> = {
  marathon: 10, tv_block: 10, movie: 20, franchise: 20, specialty: 10,
};

// Range each block occupies when numbering starts at 1 (a fresh deploy). Blocks are
// placed by accumulating sizes, so on a deploy that keeps existing channels the whole
// layout shifts up by the start number.
function blockRanges(sizes: Record<string, number>): { label: string; range: string }[] {
  let cursor = 1;
  return BLOCKS.map(({ key, label }) => {
    const size = Math.max(1, sizes[key] || BLOCK_DEFAULTS[key]);
    const range = `${cursor}–${cursor + size - 1}`;
    cursor += size;
    return { label, range };
  });
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

  const [blockSizes, setBlockSizes] = useState<Record<string, number>>({ ...BLOCK_DEFAULTS });

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
      const cb = cfg.channel_blocks || {};
      setBlockSizes({ ...BLOCK_DEFAULTS, ...cb });
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
      await api.saveConfig({ ...values, channel_blocks: blockSizes });
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

      {/* Channel numbering */}
      <Card p="lg">
        <Text fw={700} mb={4}>Channel Numbering</Text>
        <Text size="xs" c="dimmed" mb="md">
          How many channel numbers each category reserves. Blocks are placed back-to-back, so
          enlarge a category to fit more channels (handy for big libraries). Defaults are 10/10/20/20/10.
        </Text>
        <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
          {BLOCKS.map(({ key, label }) => (
            <NumberInput
              key={key}
              label={label}
              value={blockSizes[key]}
              onChange={(v) => setBlockSizes((s) => ({ ...s, [key]: Math.max(1, Number(v) || 1) }))}
              min={1}
              max={1000}
            />
          ))}
        </SimpleGrid>
        <Text size="xs" c="dimmed" mt="md">
          On a fresh deploy (numbering from 1):{' '}
          {blockRanges(blockSizes).map(({ label, range }, i) => (
            <Text span key={label}>
              {i > 0 && ' · '}{label} <Code>{range}</Code>
            </Text>
          ))}
        </Text>
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
          When enabled, channels marked “live” are re-checked on a schedule and patched in place as
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
