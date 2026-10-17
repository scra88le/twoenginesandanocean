import { expect, test } from 'vitest';
import { appTitle } from '../src/title';

test('app title', () => {
  expect(appTitle).toBe('Earth Heat Engine Map');
});
