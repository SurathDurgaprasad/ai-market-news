import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// Smoke and component tests. Components render with react-dom/server, so no
// browser environment is needed.
export default defineConfig({
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
