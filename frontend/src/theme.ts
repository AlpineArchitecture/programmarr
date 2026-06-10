import { createTheme, MantineColorsTuple } from '@mantine/core';

const orange: MantineColorsTuple = [
  '#fff4e6', '#ffe8cc', '#ffd09b', '#ffb764', '#ffa436',
  '#ff9213', '#fa8000', '#de6f00', '#c46200', '#a95200',
];

export const theme = createTheme({
  primaryColor: 'orange',
  colors: { orange },
  defaultRadius: 'sm',
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  components: {
    AppShell: {
      styles: {
        navbar: {
          backgroundColor: 'light-dark(var(--mantine-color-white), var(--mantine-color-dark-7))',
          borderRight: '1px solid light-dark(var(--mantine-color-gray-3), var(--mantine-color-dark-5))',
        },
        main: {
          backgroundColor: 'var(--app-bg)',
        },
      },
    },
    Card: {
      defaultProps: { withBorder: true },
      styles: { root: { backgroundColor: 'light-dark(var(--mantine-color-white), var(--mantine-color-dark-6))' } },
    },
  },
});
