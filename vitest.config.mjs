import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Named explicitly rather than left to the default glob: the default walks
    // the whole tree, and this repo carries example projects and scratch
    // directories that must never be mistaken for a suite.
    include: ['tools/ui-tests/**/*.test.mjs'],
    // A run that finds nothing must be a FAILURE. `vitest run` over an empty
    // set is otherwise the perfect silent pass — green, instant, and asserting
    // nothing at all. This is the default today; it is written down so a future
    // upgrade cannot flip it quietly.
    passWithNoTests: false,
    environment: 'node',
    // The suites shell out to Python and to `node --check`; a real failure must
    // not present itself as a hang.
    testTimeout: 30000,
    reporters: ['default'],
  },
});
