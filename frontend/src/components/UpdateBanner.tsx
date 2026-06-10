import { Alert, Anchor, Code, Group, Text } from '@mantine/core';
import { IconArrowUpCircle } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { version } from '../../package.json';
import { api, type UpdateInfo } from '../api/client';

const DISMISS_KEY = 'programmarr.updateDismissed';

/**
 * Polls /api/update-check once on mount and shows a banner when a newer release
 * exists. Dismissal is remembered PER VERSION (localStorage holds the dismissed
 * `latest`), so dismissing v0.6.0 stays quiet until v0.7.0 ships.
 */
export default function UpdateBanner() {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(
    () => localStorage.getItem(DISMISS_KEY),
  );

  useEffect(() => {
    api.updateCheck(version).then(setInfo).catch(() => {});
  }, []);

  if (!info?.update_available || !info.latest) return null;
  if (dismissed === info.latest) return null;

  function dismiss() {
    if (info?.latest) {
      localStorage.setItem(DISMISS_KEY, info.latest);
      setDismissed(info.latest);
    }
  }

  return (
    <Alert
      icon={<IconArrowUpCircle size={18} />}
      color="orange"
      variant="light"
      withCloseButton
      onClose={dismiss}
      mb="md"
    >
      <Group gap="xs" wrap="wrap">
        <Text size="sm" fw={600}>
          Update available: v{info.latest}
        </Text>
        {info.url && (
          <Anchor size="sm" href={info.url} target="_blank" rel="noreferrer">
            release notes
          </Anchor>
        )}
        <Text size="sm" c="dimmed">
          Pull it with <Code>docker compose pull &amp;&amp; docker compose up -d</Code>
        </Text>
      </Group>
    </Alert>
  );
}
