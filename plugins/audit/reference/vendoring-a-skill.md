# Vendoring an outside skill so that it can be pinned

A plan can pin a skill it names (`meta.skillPins`): the digest of the skill's whole
directory, as it was reviewed. A session that would load a pinned skill whose directory is
not those bytes does not start (SECURITY.md, *A pinned skill: what the pin proves, and what
it does not*). A pin needs a directory on disk that the plugin's resolver places, and a skill
from another repository or another plugin has none until it is vendored: copied into the
project and committed there. This page says how, in the order to do it.

The verb is `/audit:task skill-pin` and the reader of what it wrote is `/audit:doctor`; both
are described in full in `verbs-in-full.md`, in this directory, and this page repeats neither.

## Steps

1. **Copy the skill's directory into the project, as `.claude/skills/<name>/`; never install
   the outside plugin for one skill.** The resolver finds a bare name in the user's skills,
   then the project's `.claude/skills/`, then the running plugin's own, and reads a
   `plugin:skill` name from that plugin alone (`_skill_places.resolve_skill`). Another
   plugin's skill is therefore a name `skill-pin` cannot place, and it refuses one it cannot
   place. Installing a plugin also enables everything else it carries, not the one skill.

2. **Name the directory for what the skill does, and for nothing else.** The user's own
   directory of skills is searched before the project's, so a personal skill of the same name
   is the copy a session loads and the copy a pin is judged on; and a name the running
   plugin's own skills use is answered by the project's copy first. `skill-pin` says when the
   copy it found is a personal one - a home directory no clone carries - and refuses it unless
   `--allow-personal-copy` is passed.

3. **Read the whole text before it is committed.** Every file in the directory, not
   `SKILL.md` alone: it is instructions that an agent with a shell will follow, and the
   digest covers every file of the directory (`_skill_places.skill_digest`), scripts and
   references as much as the main file.

4. **Give it a `## Checklist` section.** A headless session started with
   `run-agent-session.py --skill` is handed the skill's frontmatter description and its
   `## Checklist` section, and the rest of the body only if the session calls the Skill tool
   for it (`skill_disclosure`). What the skill must get across has to be in those two.

5. **Take out any step that commits, pushes, spawns agents or fetches from the network.** The
   task prompt outranks a skill, and a headless session is told to name the conflict in its
   closing answer (`SKILLS_PREAMBLE`), so a skill that asks for one of these produces a
   conflict in the return and nothing else.

6. **Record where it came from, beside it.** Repository, commit and licence: pass them as
   `--source` when pinning, and the plan carries them beside the digest; keep the licence
   text in the directory.

7. **Mark the directory as not text for git, before the copy is first committed.** A checkout
   that converts line endings (`core.autocrlf`, `eol=crlf`) changes the digest of every file
   but a Markdown one: a Markdown file is read with CRLF as LF and every other file as its
   bytes. Under `core.autocrlf=true`, which is Git for Windows' default, the copy is pinned
   with the CRLF its checkout holds while git stores LF, so every clone then holds other
   bytes than the ones pinned and every wave stops. Put the line

   ```
   .claude/skills/<name>/** -text
   ```

   in the repository's `.gitattributes` before the first `git add` of the directory, and
   commit it with the directory. Adding it afterwards changes neither the blobs already
   stored nor the working copy. For a copy that was committed without it: add the line, run
   `git add --renormalize .claude/skills/<name>`, run `skill-pin <name>` again (it says so
   and writes nothing when the digest still matches, and updates the pin when it does not),
   and commit the attribute, the renormalized copy and the plan together.

8. **Pin it, and commit the directory with the plan.**

   ```
   /audit:task skill-pin <name> --source "<repository>@<commit>, <licence>"
   ```

   The verb prints one line holding the digest it pinned, the directory it read and the
   record it wrote, and a re-pin's line holds the old digest and the new one. A `WARNING:`
   line follows it for each of: a personal copy pinned on `--allow-personal-copy` (the pin
   fails on every machine without that copy), a bytecode cache, `.DS_Store` or `.git` in the
   directory, and a skill the plan names nowhere (the pin protects nothing). A pin with
   none of those prints no `WARNING:` line. The verb refuses - writing nothing - a name
   nothing resolves, a directory with no digest (it prints the entry and its kind) and an
   unflagged personal copy. `/audit:doctor`'s `skill pins` rows then say, for each pinned
   skill, whether it matches, does not match, cannot be found or cannot be read whole; which
   pins nothing names any more (stale); and which skills the plan names that nothing pins.

9. **Keep the bytes the bytes.**
   - A bytecode cache or a `.DS_Store` written into the directory after pinning makes the pin
     mismatch, and the mismatch row names it. Run the skill's scripts with
     `PYTHONDONTWRITEBYTECODE=1` (the plugin's own session runner does) and remove what a
     tool left behind.
   - A wave's sessions each run in a tree cut from a commit and load that commit's copy, so
     bytes restored in the working copy count only once committed, while a session run in
     this tree and a subagent dispatched from it read the working copy. `/audit:doctor`
     prints a `skill pins` row for each route, opening `for <route>:` - `a session run in
     this tree` or `a subagent dispatched from this tree`, and `a wave's sessions` - and a
     WARNING row for a route whose copy is not the bytes pinned, in the words `the skill
     <name> is pinned, and the copy an agent or a session would load is not the bytes
     pinned: <path> has digest <digest>, the plan pinned <digest>`. A pinned skill edited
     after its commit warns on the first two routes and matches on the wave's.

10. **To upgrade, replace the directory, read the diff, and pin again.** Copy the new version
    over the old one so that a file the new version dropped is gone too, read `git diff` of
    the directory as carefully as the first copy, and run `skill-pin` again: its line holds
    the old and the new digest, and the verb journals them.

## What a pin does not buy

A pin proves the bytes are the ones pinned, not that they are safe; the whole statement, and
what else it does not cover, is SECURITY.md's section named above and is not repeated here.
A skill being invoked is never evidence that its workflow was followed: the session's record
(`skillsInvoked`) says only that its Skill tool named the skill. The plan's gates are what
check the work.

## Checklist

- [ ] the skill's directory copied to `.claude/skills/<name>/`, the outside plugin not installed
- [ ] the name says what the skill does and collides with nothing built in or personal
- [ ] every file read before commit, steps that commit, push, spawn agents or fetch removed
- [ ] a `## Checklist` section in `SKILL.md`
- [ ] repository, commit and licence passed as `--source`, the licence text kept beside it
- [ ] `.claude/skills/<name>/** -text` in `.gitattributes` before the directory is first
      added; a copy committed without it: the line, `git add --renormalize`, a re-pin, a commit
- [ ] `/audit:task skill-pin <name>` run, its `WARNING:` lines (if any) read, and the
      directory committed with the plan
- [ ] `/audit:doctor`'s `skill pins` rows read
