import { Box, ScrollArea, Text } from '@mantine/core';
import { useEffect, useRef } from 'react';

interface Props {
  lines: string[];
  done: boolean;
  success?: boolean;
  height?: number;
}

export default function TerminalOutput({ lines, done, success, height = 320 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines]);

  return (
    <Box
      style={{
        backgroundColor: '#0d0e0f',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--mantine-radius-sm)',
        overflow: 'hidden',
      }}
    >
      {/* Terminal chrome bar */}
      <Box
        style={{
          backgroundColor: 'var(--mantine-color-dark-6)',
          borderBottom: '1px solid var(--border-subtle)',
          padding: '6px 12px',
          display: 'flex',
          gap: 6,
        }}
      >
        {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
          <Box key={c} style={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: c }} />
        ))}
      </Box>

      <ScrollArea h={height} viewportRef={ref} p={0}>
        <Box p="md" style={{ fontFamily: 'ui-monospace, "Cascadia Code", "Fira Code", monospace', fontSize: 12 }}>
          {lines.length === 0 && !done && (
            <Text size="xs" c="dimmed" style={{ fontFamily: 'inherit' }}>Waiting for output...</Text>
          )}
          {lines.map((line, i) => (
            <Text
              key={i}
              size="xs"
              style={{ fontFamily: 'inherit', whiteSpace: 'pre-wrap', color: '#d4d4d4', lineHeight: 1.6 }}
            >
              {line || ' '}
            </Text>
          ))}
          {done && (
            <Text
              size="xs"
              fw={700}
              mt="xs"
              style={{ fontFamily: 'inherit' }}
              c={success ? 'green.4' : 'red.4'}
            >
              {success ? '● Process exited successfully' : '● Process exited with errors'}
            </Text>
          )}
        </Box>
      </ScrollArea>
    </Box>
  );
}
