# The README demo: a real Claude Code session meeting the plan gate.
#
# Run it through `python3 tools/capture-demo-gif.py --record`, never on its own. That
# tool builds the demo project at /tmp/acme-store-demo and a copy of this checkout's
# plugin plus an isolated settings file at /tmp/acme-store-demo-kit, runs this tape
# from the kit directory, and only ships the GIF once it has replayed the refused
# edit against the gate and found no personal data in any frame. Run alone, this
# tape has no project to open.
#
# Every path here is neutral on purpose: Claude Code prints the project path in its
# header and the plugin path in every command it runs, and the GIF is public.
#
# EVERY WAIT PROVES ONE STEP HAPPENED, rather than sleeping and hoping. Claude Code
# ends each finished turn with a line like "* Brewed for 7s - done 12:11 AM", so a
# regex spanning the step's own output and THAT line (`(?s)...`) is only true once
# the turn it belongs to has finished - an earlier turn's line cannot satisfy it.
# Every Wait on camera also accepts the account's usage-limit screen, so a take that
# hits the limit runs to its end in seconds instead of timing out at each step, and
# the recording tool then refuses it naming the limit as the cause.

Output demo-gate.gif
Output demo-gate.txt

Require claude

Set Shell "bash"
# THE WHOLE TAKE HAS TO FIT ON ONE SCREEN. VHS 0.12.1 reads a screen - for every
# Wait and for its text output alike - as the first rows of the terminal buffer, as
# many as the window is tall, so once the session scrolls, nothing below that is
# read: not the line a Wait waits for, and not the refusal. The window is sized for
# the whole scenario; re-derive its rows and columns by running
# `echo $(tput lines) $(tput cols)` in a throwaway tape with these three settings.
# The width is the one a README column scales least: the GIF is shown at the
# column's width, so every pixel of width past it shrinks the text further. The
# height costs no legibility - a README scales by width alone - and is sized with
# room to spare over the tallest recorded take, because Claude's last reply varies
# in length from take to take and a take one row too tall is refused.
Set FontSize 14
Set Width 1200
Set Height 2050
Set Padding 20
Set TypingSpeed 45ms
Set WaitTimeout 4m

# --- launch, off camera -----------------------------------------------------------
# The recording tool starts VHS with the caller's own Claude Code session variables
# removed and the demo's switches added (see session_env()). The user's own settings
# are not loaded (--setting-sources) and no MCP server of theirs is
# (--strict-mcp-config). With CLAUDE_CODE_OAUTH_TOKEN set, the tool also points
# CLAUDE_CONFIG_DIR at a config of the take's own under the kit, removed afterwards;
# without it the take runs in the operator's own config, and the tool lists what it
# left there (see config_plan()).
#
# WHICH PERMISSION MODE THE FOOTER SHOWS, AND WHY. No mode is chosen here, in the
# settings file, or in the take's config, and `tape_problems()` refuses a tape that
# names one. The footer shows Claude Code's own starting mode: "With Claude Code
# v2.1.283 or later, auto mode is the built-in starting permission mode for
# interactive terminal and VS Code sessions."
# (https://code.claude.com/docs/en/permission-modes)
Hide
Type "export PS1='$ ' HISTFILE=/dev/null; cd /tmp/acme-store-demo && clear"
Enter

# FIRST LAUNCH: TRUST THE FOLDER. Claude Code loads no plugin or settings hook in a
# folder it has not been told to trust - and the plan gate is a hook. IS_DEMO skips
# the trust question without granting trust (read from the 2.1.292 binary's trust
# and hook-registration code), so this launch runs without it, answers the question,
# and exits. The answer is stored by Claude Code itself, as for any user, in the
# config the take was handed - its own, removed afterwards, or the operator's, where
# the tool names the entry once the take ends; a folder already trusted asks
# nothing, and the keys below then land on an empty prompt.
# The question opens with "No, exit" selected, so Down moves to "Yes, I trust this
# folder" before Enter.
Type "env -u IS_DEMO claude --model sonnet --plugin-dir /tmp/acme-store-demo-kit/audit --settings /tmp/acme-store-demo-kit/settings.json --setting-sources project,local --strict-mcp-config"
Enter
Wait+Screen@60s /Quick safety check|shift\+tab to cycle/
Sleep 2s
Down
Sleep 500ms
Enter
Wait+Screen@60s /shift\+tab to cycle/
Type "/exit"
Sleep 1s
Enter
Wait+Screen@30s /(?m)^\$ *$/

# SECOND LAUNCH: the recorded session, in the trusted folder, with IS_DEMO. `clear`
# first, so neither launch line is left on screen above the header.
Type "clear; claude --model sonnet --plugin-dir /tmp/acme-store-demo-kit/audit --settings /tmp/acme-store-demo-kit/settings.json --setting-sources project,local --strict-mcp-config"
Enter
Wait+Screen@60s /shift\+tab to cycle/
# The welcome header is recorded as a user sees it. IS_DEMO is Claude Code's
# documented recording mode: it hides the email and the organisation name and keeps
# the version, model and plan line. No /clear: it starts a second conversation and
# prints the header again.
Show

# --- the plan -------------------------------------------------------------------
# Typed off camera, shown once it is in the box. Typing "/" opens the full command
# list, and every key after it refilters and repaints all of it: in the first take
# that got this far those few frames were most of the file's bytes (read with
# ffprobe's per-packet sizes). The reader still sees the command in the box, the
# narrowed list under it, and the Enter.
Sleep 1s
Hide
Type "/audit:status"
Sleep 1500ms
Show
Sleep 1500ms
Enter
Wait+Screen /(?s)READY NOW.*for \d+s · done|hit your session limit|Usage limit reached/
Sleep 5s
# BEFORE EVERY PROMPT, THE INPUT BOX MUST HAVE THE KEYS. Claude Code can open a
# dialog of its own at the end of a turn - a recommendation with numbered options -
# and keys typed then answer the dialog instead of reaching the prompt. Escape
# dismisses such a dialog; on an idle, empty prompt the chat:cancel handlers in the
# 2.1.292 keymap act on nothing. The Wait then proves the live input box is back and
# EMPTY: the prompt mark alone on a row - at most a no-break space or the "Try ..."
# placeholder after it - directly between the box's two border rows. A sent prompt's
# echo has text after the mark and no border round it; a dialog's options and the
# command popup are indented; a box already holding text does not match either. The
# pattern was checked in VHS against recorded screens: an empty box matched, an open
# dialog and a box holding typed text timed out.
Escape
Sleep 1s
Wait+Screen@60s /(?s)READY NOW.*for \d+s · done.*\n─{20,} *\n❯[ \x{00A0}]*(Try "[^"\n]*")? *\n─{20,}|hit your session limit|Usage limit reached/

# --- an edit the plan covers: P2.1 owns src/checkout.ts ---------------------------
# Submission: a pause for the input to settle, Escape to close any completion popup
# the typed path may have opened, a pause longer than a double press, then Enter. In
# the 2.1.292 keymap Escape is autocomplete:dismiss while a popup is open; with none
# open and nothing running, the chat:cancel handlers read there act on nothing.
# The Wait right after proves the turn started, so a prompt left unsent fails here,
# by name, not four minutes later.
Type "Validate the payload in src/checkout.ts: checkout() should reject anything that is not an object with an items array."
Sleep 1500ms
Escape
Sleep 1500ms
Enter
Wait+Screen@60s /esc to interrupt|(Update|Write|Read)\([^)]*checkout\.ts\)|hit your session limit|Usage limit reached/
Wait+Screen /(?s)(Update|Write)\([^)]*checkout\.ts\).*for \d+s · done|hit your session limit|Usage limit reached/
Sleep 5s
Escape
Sleep 1s
Wait+Screen@60s /(?s)(Update|Write)\([^)]*checkout\.ts\).*for \d+s · done.*\n─{20,} *\n❯[ \x{00A0}]*(Try "[^"\n]*")? *\n─{20,}|hit your session limit|Usage limit reached/

# --- an edit no task covers, while the phase is running ---------------------------
# Large on purpose: the gate lets the first small out-of-plan file in a session
# through, so a one-line change would show the allowance, not the refusal. No digit
# in any prompt: a digit typed while a numbered dialog has the keys picks an option.
Type "Now rewrite src/billing.ts as a full invoicing module: line items, tax, discounts and totals, each with a doc comment - around a hundred and twenty lines."
Sleep 1500ms
Escape
Sleep 1500ms
Enter
Wait+Screen@60s /(?s)checkout\.ts.*(esc to interrupt|(Update|Write|Read)\([^)]*billing\.ts\))|hit your session limit|Usage limit reached/
Wait+Screen /(?s)(Update|Write)\([^)]*billing\.ts\).*Outside the running plan|hit your session limit|Usage limit reached/

# --- the end: the refusal and Claude's reading of it, nothing after -------------
# In the recorded take, after the refusal Claude explained it in a line, then acted
# on the gate's
# advice by adding a task. How far that goes is the
# model's choice, so its height is not bounded by anything this tape controls, and
# the take has to fit one screen. So the take ends on the explanation: wait for
# Claude's first line after the refusal - its one-line reading of it in the one
# recorded take that got this far, and a tool call if it ever goes straight to one, which still ends the
# take with the refusal on screen rather than timing it out - give it a moment to
# finish, and interrupt. The last Wait proves the end state before the hold: the
# turn interrupted, or already finished on its own, and the input box empty again.
Wait+Screen@90s /(?s)Outside the running plan.*\n⏺ [^\n]+|hit your session limit|Usage limit reached/
Sleep 3s
Escape
Wait+Screen@60s /(?s)Outside the running plan.*(Interrupted|for \d+s · done).*\n─{20,} *\n❯[ \x{00A0}]*(Try "[^"\n]*")? *\n─{20,}|hit your session limit|Usage limit reached/
# Hold on the end: it is the point of the recording.
Sleep 12s
