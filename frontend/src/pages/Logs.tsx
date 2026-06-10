import {
  Badge, Box, Card, Code, Group, Loader,
  Stack, Text, Title, UnstyledButton,
} from '@mantine/core';
import { IconChevronDown, IconChevronRight, IconFileText } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { api, LogEntry } from '../api/client';

function tagFromName(name: string): { label: string; color: string } {
  if (name.startsWith('export'))      return { label: 'Export',      color: 'blue' };
  if (name.startsWith('no_ai'))       return { label: 'No-AI',       color: 'teal' };
  if (name.startsWith('collections')) return { label: 'Collections', color: 'violet' };
  if (name.startsWith('probe'))       return { label: 'Probe',       color: 'gray' };
  if (name.startsWith('deploy'))      return { label: 'Deploy',      color: 'orange' };
  if (name.startsWith('images'))      return { label: 'Images',      color: 'pink' };
  if (name.startsWith('sync'))        return { label: 'Sync',        color: 'green' };
  return { label: 'Run', color: 'gray' };
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

function LogRow({ entry }: { entry: LogEntry }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const tag = tagFromName(entry.name);

  async function toggle() {
    if (!open && content === null) {
      const data = await api.getLog(entry.name);
      setContent(data.content);
    }
    setOpen((v) => !v);
  }

  return (
    <Card p={0} mb="xs">
      <UnstyledButton
        onClick={toggle}
        style={{ width: '100%', padding: '12px 16px' }}
      >
        <Group gap="sm">
          <IconFileText size={16} color="var(--mantine-color-dimmed)" />
          <Badge color={tag.color} variant="light" size="sm">{tag.label}</Badge>
          <Text size="sm" style={{ flex: 1 }} truncate>{entry.name}</Text>
          <Text size="xs" c="dimmed">{formatDate(entry.modified)}</Text>
          {open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
        </Group>
      </UnstyledButton>

      {open && (
        <Box
          p="md"
          pt={0}
          style={{ borderTop: '1px solid var(--border-subtle)' }}
        >
          {content === null ? (
            <Loader size="xs" mt="sm" />
          ) : (
            <Code
              block
              style={{ fontSize: 11, maxHeight: 400, overflow: 'auto', backgroundColor: '#0d0e0f', color: '#d4d4d4' }}
            >
              {content}
            </Code>
          )}
        </Box>
      )}
    </Card>
  );
}

export default function Logs() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getLogs().then((l) => { setLogs(l); setLoading(false); });
  }, []);

  return (
    <Stack gap="lg">
      <Title order={2}>Logs</Title>

      {loading ? (
        <Stack align="center" justify="center" h={200}><Loader color="orange" /></Stack>
      ) : logs.length === 0 ? (
        <Card p="xl">
          <Stack align="center" gap="xs">
            <IconFileText size={32} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed">No logs yet — run the pipeline first</Text>
          </Stack>
        </Card>
      ) : (
        <Box>
          {logs.map((e) => <LogRow key={e.name} entry={e} />)}
        </Box>
      )}
    </Stack>
  );
}
