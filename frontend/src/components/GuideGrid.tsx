import { Box, Card, Group, Stack, Text, Tooltip } from '@mantine/core';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Guide, GuideProgramme } from '../api/client';

const PX_PER_MIN = 3;          // 1 hour = 180px
const RAIL_WIDTH = 190;        // left channel rail
const ROW_HEIGHT = 56;         // px per channel row
const HEADER_HEIGHT = 32;      // time axis header height
const WINDOW_HOURS = 3;        // hours visible before horizontal scroll

// Cycling palette for programme blocks
const BLOCK_COLORS = [
  'var(--mantine-color-teal-8)',
  'var(--mantine-color-blue-8)',
  'var(--mantine-color-violet-8)',
  'var(--mantine-color-indigo-8)',
  'var(--mantine-color-cyan-8)',
  'var(--mantine-color-grape-8)',
];

function floorToHalfHour(d: Date): Date {
  const out = new Date(d);
  out.setMinutes(d.getMinutes() < 30 ? 0 : 30, 0, 0);
  return out;
}

function minutesBetween(a: Date, b: Date): number {
  return (b.getTime() - a.getTime()) / 60000;
}

function fmtTime(d: Date): string {
  const h = d.getHours();
  const m = d.getMinutes();
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 || 12;
  return m === 0 ? `${h12} ${ampm}` : `${h12}:${m.toString().padStart(2, '0')}`;
}

interface ProgrammeBlock {
  prog: GuideProgramme;
  left: number;   // px from anchor
  width: number;  // px
  color: string;
}

export function GuideGrid({
  guide,
  onRefresh,
}: {
  guide: Guide;
  onRefresh?: () => void;
}) {
  const nav = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLDivElement>(null);
  const [nowOffset, setNowOffset] = useState(0);
  const [anchor] = useState(() => floorToHalfHour(new Date()));

  // Update the "now" line position every 30 seconds
  useEffect(() => {
    function update() {
      setNowOffset(minutesBetween(anchor, new Date()) * PX_PER_MIN);
    }
    update();
    const id = setInterval(update, 30_000);
    return () => clearInterval(id);
  }, [anchor]);

  // Scroll "now" into view on mount — position it ~1/4 from the left
  useEffect(() => {
    if (scrollRef.current) {
      const target = Math.max(0, nowOffset - (scrollRef.current.clientWidth * 0.25));
      scrollRef.current.scrollLeft = target;
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!guide.channels.length) {
    return null; // parent renders empty/error state
  }

  const totalMinutes = WINDOW_HOURS * 60 * 2; // feed window is wider than viewport
  const contentWidth = Math.max(
    totalMinutes * PX_PER_MIN,
    // ensure feed programmes fit
    ...guide.programmes.map((p) =>
      minutesBetween(anchor, new Date(p.stop)) * PX_PER_MIN
    ),
  );

  // Build time labels every 30 min
  const timeLabels: { label: string; left: number }[] = [];
  for (let m = 0; m <= totalMinutes; m += 30) {
    const d = new Date(anchor.getTime() + m * 60000);
    timeLabels.push({ label: fmtTime(d), left: m * PX_PER_MIN });
  }

  // Build programme blocks per channel
  const blocksByChannel = new Map<number, ProgrammeBlock[]>();
  guide.channels.forEach((ch, idx) => {
    const color = BLOCK_COLORS[idx % BLOCK_COLORS.length];
    const progs = guide.programmes
      .filter((p) => p.number === ch.number)
      .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());

    const blocks: ProgrammeBlock[] = [];
    for (const prog of progs) {
      const start = new Date(prog.start);
      const stop = new Date(prog.stop);
      const left = minutesBetween(anchor, start) * PX_PER_MIN;
      const width = minutesBetween(start, stop) * PX_PER_MIN;
      if (width < 1) continue;
      blocks.push({ prog, left, width, color });
    }
    blocksByChannel.set(ch.number, blocks);
  });

  return (
    <Box style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', border: '1px solid var(--mantine-color-dark-4)', borderRadius: 8 }}>
      {/* Header row: empty rail + time axis */}
      <Box style={{ display: 'flex', flexShrink: 0 }}>
        {/* Rail header */}
        <Box style={{
          width: RAIL_WIDTH, minWidth: RAIL_WIDTH, height: HEADER_HEIGHT,
          borderRight: '1px solid var(--mantine-color-dark-4)',
          borderBottom: '1px solid var(--mantine-color-dark-4)',
          background: 'var(--mantine-color-dark-7)',
          flexShrink: 0,
        }} />
        {/* Time labels — mirrors the scrollable content area */}
        <Box
          ref={scrollRef}
          style={{ flex: 1, overflowX: 'auto', overflowY: 'hidden' }}
        >
          <Box style={{ position: 'relative', width: contentWidth, height: HEADER_HEIGHT, background: 'var(--mantine-color-dark-7)', borderBottom: '1px solid var(--mantine-color-dark-4)' }}>
            {timeLabels.map(({ label, left }) => (
              <Text
                key={left}
                size="xs"
                c="dimmed"
                style={{
                  position: 'absolute',
                  left: left + 4,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  whiteSpace: 'nowrap',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {label}
              </Text>
            ))}
            {/* Half-hour tick marks */}
            {timeLabels.map(({ left }) => (
              <Box
                key={`tick-${left}`}
                style={{
                  position: 'absolute',
                  left,
                  top: 0,
                  bottom: 0,
                  width: 1,
                  background: 'var(--mantine-color-dark-4)',
                }}
              />
            ))}
          </Box>
        </Box>
      </Box>

      {/* Channel rows */}
      <Box style={{ display: 'flex', maxHeight: 480, overflow: 'hidden' }}>
        {/* Left rail — vertical scroll is driven by JS sync from the programme grid,
            so the rail and the grid share a single scrollbar (on the grid). */}
        <Box
          ref={railRef}
          onWheel={(e) => {
            // Rail has no scrollbar of its own; forward wheel to the grid scroller.
            const body = railRef.current?.parentElement?.querySelector('[data-grid-scroll]') as HTMLDivElement | null;
            if (body) body.scrollTop += e.deltaY;
          }}
          style={{ width: RAIL_WIDTH, minWidth: RAIL_WIDTH, overflowY: 'hidden', flexShrink: 0, borderRight: '1px solid var(--mantine-color-dark-4)' }}
        >
          {guide.channels.map((ch) => (
            <Box
              key={ch.number}
              onClick={() => nav(`/channels/${ch.number}`)}
              style={{
                height: ROW_HEIGHT,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '0 10px',
                cursor: 'pointer',
                borderBottom: '1px solid var(--mantine-color-dark-5)',
                background: 'var(--mantine-color-dark-7)',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--mantine-color-dark-6)'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--mantine-color-dark-7)'; }}
            >
              {ch.icon && (
                <Box
                  component="img"
                  src={ch.icon}
                  alt=""
                  style={{ width: 28, height: 28, objectFit: 'contain', flexShrink: 0, borderRadius: 4 }}
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                />
              )}
              <Stack gap={1} style={{ minWidth: 0 }}>
                <Text size="xs" fw={700} c="dimmed" style={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
                  {ch.number}
                </Text>
                <Text size="xs" fw={600} truncate style={{ lineHeight: 1.2 }}>
                  {ch.name.replace(new RegExp(`^#?\\s*${ch.number}\\b[\\s.\\-:]*`), '')}
                </Text>
              </Stack>
            </Box>
          ))}
        </Box>

        {/* Programme grid — scrolls in sync with header via JS scroll sync */}
        <SyncedScroll headerRef={scrollRef} railRef={railRef} style={{ flex: 1, overflowX: 'auto', overflowY: 'auto' }}>
          <Box style={{ position: 'relative', width: contentWidth, minHeight: guide.channels.length * ROW_HEIGHT }}>
            {/* Vertical half-hour grid lines */}
            {timeLabels.map(({ left }) => (
              <Box
                key={`vline-${left}`}
                style={{
                  position: 'absolute',
                  left,
                  top: 0,
                  bottom: 0,
                  width: 1,
                  background: 'var(--mantine-color-dark-5)',
                  pointerEvents: 'none',
                }}
              />
            ))}

            {/* "Now" line */}
            {nowOffset > 0 && (
              <Box style={{
                position: 'absolute',
                left: nowOffset,
                top: 0,
                bottom: 0,
                width: 2,
                background: 'var(--mantine-color-orange-5)',
                zIndex: 10,
                pointerEvents: 'none',
              }} />
            )}

            {/* Programme blocks per channel row */}
            {guide.channels.map((ch, rowIdx) => {
              const blocks = blocksByChannel.get(ch.number) ?? [];
              return (
                <Box
                  key={ch.number}
                  style={{
                    position: 'absolute',
                    top: rowIdx * ROW_HEIGHT,
                    left: 0,
                    right: 0,
                    height: ROW_HEIGHT,
                    borderBottom: '1px solid var(--mantine-color-dark-5)',
                  }}
                >
                  {blocks.map(({ prog, left, width, color }) => (
                    <ProgrammeBlock
                      key={`${prog.start}-${prog.title}`}
                      prog={prog}
                      left={left}
                      width={width}
                      color={color}
                    />
                  ))}
                </Box>
              );
            })}
          </Box>
        </SyncedScroll>
      </Box>
    </Box>
  );
}

function ProgrammeBlock({ prog, left, width, color }: ProgrammeBlock) {
  const startFmt = new Date(prog.start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const stopFmt = new Date(prog.stop).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

  const inner = (
    <Box
      style={{
        position: 'absolute',
        left: left + 1,
        top: 3,
        height: ROW_HEIGHT - 7,
        width: Math.max(width - 2, 2),
        background: color,
        borderRadius: 4,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '0 6px',
        cursor: 'default',
      }}
    >
      <Text size="xs" fw={600} truncate style={{ color: 'rgba(255,255,255,0.95)', lineHeight: 1.2 }}>
        {prog.title}
      </Text>
      {prog.episode && width > 80 && (
        <Text size="xs" truncate style={{ color: 'rgba(255,255,255,0.65)', lineHeight: 1.2 }}>
          {prog.episode}
        </Text>
      )}
    </Box>
  );

  if (width < 40) return inner;

  return (
    <Tooltip
      label={
        <Stack gap={2}>
          <Text size="xs" fw={600}>{prog.title}</Text>
          {prog.episode && <Text size="xs">{prog.episode}</Text>}
          <Text size="xs" c="dimmed">{startFmt} – {stopFmt}</Text>
        </Stack>
      }
      withArrow
      position="top"
    >
      {inner}
    </Tooltip>
  );
}

// Keeps the programme grid scroll in sync with the time-axis header (horizontal)
// and the left channel rail (vertical), so the whole grid reads as one scroller.
function SyncedScroll({
  headerRef,
  railRef,
  children,
  style,
}: {
  headerRef: React.RefObject<HTMLDivElement | null>;
  railRef?: React.RefObject<HTMLDivElement | null>;
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const body = ref.current;
    const head = headerRef.current;
    if (!body || !head) return;

    function onBodyScroll() {
      if (head) head.scrollLeft = body!.scrollLeft;
      if (railRef?.current) railRef.current.scrollTop = body!.scrollTop;
    }
    function onHeadScroll() {
      if (body) body.scrollLeft = head!.scrollLeft;
    }

    body.addEventListener('scroll', onBodyScroll);
    head.addEventListener('scroll', onHeadScroll);
    return () => {
      body.removeEventListener('scroll', onBodyScroll);
      head.removeEventListener('scroll', onHeadScroll);
    };
  }, [headerRef, railRef]);

  return (
    <div ref={ref} data-grid-scroll style={style}>
      {children}
    </div>
  );
}
