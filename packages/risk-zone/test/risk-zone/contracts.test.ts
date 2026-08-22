import { describe, expect, it } from 'vitest';
import { CONDITIONAL_CONNECTIVITY_DISCLAIMER } from '../../src/index.js';

describe('conditional connectivity result contract', () => {
  it('identifies the output as a non-blockage estimate', () => {
    expect(CONDITIONAL_CONNECTIVITY_DISCLAIMER).toContain('not an estimate of organism abundance');
    expect(CONDITIONAL_CONNECTIVITY_DISCLAIMER).toContain('intake blockage probability');
  });
});
