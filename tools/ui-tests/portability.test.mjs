// The portability levers, RUN rather than read.
//
// Every one of them is a conditional, and a conditional has two wrong versions:
// it never fires, or it always fires. A substring pin over the assembled page can
// say `pickableSkills` exists; it cannot say that 'warn' offers what 'strict'
// withholds, which is the whole feature. Nor can it say that an UNKNOWN verdict
// is offered rather than hidden — the difference between a missing basis and a
// decision, which the grading itself refuses to blur.
//
// The table is deliberately NOT filtered and the pickers are, so both are checked
// here against one registry: a change that filtered the table would look correct
// in a screenshot and would read, to whoever hit it, as "you do not have that
// skill".
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const panel = loadPanel();
const { portabilityMode, travels, pickableSkills, portabilityHints,
  spelledSkills } =
  reach(panel.ctx, ['portabilityMode', 'travels', 'pickableSkills',
    'portabilityHints', 'spelledSkills']);

// One registry for every case, carrying all three verdicts. A fixture with only
// two of them cannot tell "hide what does not travel" from "hide what is not
// known to travel", which is the mutation `travels` exists to prevent.
const REG_ROWS = [
  { name: 'vendored', source: 'project', travels: true,
    travelsBasis: 'committed under .claude/, so a clone gets it' },
  { name: 'personal', source: 'user', travels: false,
    travelsBasis: 'lives in a home directory, which no clone carries' },
  { name: 'unreadable', source: 'plugin', travels: null,
    travelsBasis: 'the committed .claude/settings.json could not be read' },
];

// `REG` and `STATE` are top-level `let` bindings in the concatenated script, so
// they are NOT properties of the vm's global object and assigning through
// `ctx.REG` writes a shadow nothing reads. Assigned as source, the way
// initial-tab.test.mjs already does.
function assign(name, value) {
  vm.runInContext(name + ' = ' + JSON.stringify(value) + ';', panel.ctx);
}

function setUp(mode, spelled) {
  assign('REG', { skills: REG_ROWS, agents: [], mcp: [] });
  assign('STATE', {
    config: mode === undefined ? {} : { portability: mode },
    defaults: { portability: 'strict' },
    composition: { tasks: [{ skills: spelled || [] }], areaSkills: [] },
  });
}

describe('portabilityMode', () => {
  it('reads the project config when it sets one', () => {
    setUp('warn');
    expect(portabilityMode()).toBe('warn');
  });

  // The shipped default arrives in the payload. A literal here would be a second
  // statement of a value the schema, the validator and the hooks already agree
  // on, and the one most likely to be forgotten when it changes.
  it('falls back to the shipped default, which comes from the payload', () => {
    setUp(undefined);
    expect(portabilityMode()).toBe('strict');
    vm.runInContext('STATE.defaults = {portability:"off"};', panel.ctx);
    expect(portabilityMode()).toBe('off');
  });
});

describe('travels', () => {
  it('refuses only a verdict of false', () => {
    expect(travels({ travels: true })).toBe(true);
    expect(travels({ travels: false })).toBe(false);
  });

  // THE CASE THAT LOOKS VACUOUS AND IS NOT. `=== true` passes every other case
  // here and fails this one, and it is the difference between a missing basis
  // and a decision: an unreadable settings file is not evidence about a plugin.
  it('offers an UNKNOWN verdict rather than treating it as a refusal', () => {
    expect(travels({ travels: null })).toBe(true);
    expect(travels({})).toBe(true);
  });
});

describe('pickableSkills', () => {
  it('withholds what would not travel, under strict', () => {
    setUp('strict');
    expect(pickableSkills().map((s) => s.name))
      .toEqual(['vendored', 'unreadable']);
  });

  // THE SECOND DIRECTION, and the only case that fails when the filter becomes
  // unconditional — the natural way to make the case above green.
  it('offers everything under warn and off', () => {
    setUp('warn');
    expect(pickableSkills()).toHaveLength(REG_ROWS.length);
    setUp('off');
    expect(pickableSkills()).toHaveLength(REG_ROWS.length);
  });
});

describe('portabilityHints', () => {
  it('names a spelled skill that resolves here and would not travel', () => {
    setUp('strict', ['personal']);
    expect(portabilityHints())
      .toEqual([{ name: 'personal', basis: REG_ROWS[1].travelsBasis }]);
  });

  // A verdict without its basis is what a reader cannot act on, so the basis is
  // asserted as content rather than as a key that happens to exist.
  it('carries the basis, not merely the name', () => {
    setUp('strict', ['personal']);
    expect(portabilityHints()[0].basis).toContain('home directory');
  });

  // THREE SECOND-DIRECTION CASES. A note that fired on everything spelled, on
  // every verdict, or in every mode would pass the two above and fail these.
  it('says nothing about a name that travels, or one that is merely unknown', () => {
    setUp('strict', ['vendored', 'unreadable']);
    expect(portabilityHints()).toEqual([]);
  });

  it('says nothing about a name the manifest does not spell', () => {
    setUp('strict', []);
    expect(portabilityHints()).toEqual([]);
  });

  it('says nothing at all when portability is off', () => {
    setUp('off', ['personal']);
    expect(portabilityHints()).toEqual([]);
  });

  // An empty inventory is a scan that could not answer, not a clean manifest —
  // the same distinction skillHints draws one note over.
  it('says nothing when there was no inventory to judge against', () => {
    setUp('strict', ['personal']);
    assign('REG', { skills: [], agents: [], mcp: [] });
    expect(portabilityHints()).toEqual([]);
  });
});

describe('spelledSkills', () => {
  it('reads task skills and area defaults together, sorted and deduped', () => {
    setUp('strict', ['b', 'a', 'b']);
    vm.runInContext('STATE.composition.areaSkills = ["c","a"];', panel.ctx);
    expect(spelledSkills()).toEqual(['a', 'b', 'c']);
  });
});
