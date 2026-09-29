---
name: tri-web Preflight Board
description: A dark-first instrument board that shows each condition against the athlete's own limits, then states the day's readiness level.
colors:
  surface: "#0b0f14"
  surface-2: "#111820"
  ink: "#d9dee5"
  ink-2: "#95a0ae"
  line: "#2e3d52"
  go: "#5fd38d"
  easy: "#f2c14e"
  rest: "#ff8f6b"
  hold: "#8fb8ff"
  danger: "#ef6a63"
  on-fill: "#0b0f14"
typography:
  level-word:
    fontFamily: "system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.12em"
  figure:
    fontFamily: "system-ui, sans-serif"
    fontSize: "2.25rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.025em"
    fontFeature: "tnum"
  unit:
    fontFamily: "system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    fontFeature: "tnum"
  body:
    fontFamily: "system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    fontFeature: "tnum"
  label:
    fontFamily: "system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    letterSpacing: "0.05em"
rounded:
  sm: "6px"
  md: "8px"
  full: "9999px"
spacing:
  xs: "8px"
  sm: "12px"
  md: "20px"
  lg: "24px"
components:
  condition-row-header:
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    padding: "12px 12px 12px 12px"
  readiness-container:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "16px 20px"
  reason-chip:
    textColor: "{colors.rest}"
    rounded: "{rounded.full}"
    height: "28px"
    padding: "0 12px"
  hold-line-button:
    textColor: "{colors.hold}"
    rounded: "{rounded.sm}"
    height: "32px"
    padding: "0 12px"
  view-toggle:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    height: "28px"
---

# Design System: tri-web Preflight Board

## Overview

**Creative North Star: "The Preflight Board"**

Each morning is a preflight. The board states the conditions first, each against the athlete's own limits, and the readiness level sits directly below them as the call those conditions produced. It is an instrument panel, not a dashboard: a near-black ground, instrument-white figures, thin rules, and status spoken in words. It is read at 5 AM in a dark room, so dark is the first-class scheme and a daylight board overrides it under a light system preference.

The board is one column of ruled bands (conditions, readiness, hold line, plan, week), not a grid of equal tiles. The only container with a fill is the readiness block, and it is quiet. Figures carry the weight; everything else steps back to grey ink.

The web app only maps the server's words to colour. It never compares a value against a limit itself.

**Key Characteristics:**
- Dark-first, with a daylight variant that keeps the same roles.
- Flat: tonal layering and hairlines, no shadows.
- Tabular numerals everywhere; platform sans, no web fonts.
- Status colour is always an addition to a spoken word.
- Single-column board, `max-w-5xl`, bands separated by 1px rules.

## Colors

A cool blue-black ground with grey ink and four status hues, each of which always appears beside its word.

### Primary
- **Hold Blue** (#8fb8ff): the "outside your band but not flagged" state, the active-row wash (10% tint), focus rings, the active tab underline, the HOLD line and the pending-review badge.

### Secondary
- **Go Green** (#5fd38d): a row inside its own band, and readiness high or prime.
- **Easy Amber** (#f2c14e): a caution reason, and readiness moderate.
- **Rest Coral** (#ff8f6b): a stop reason, and readiness poor or low.

### Neutral
- **Instrument Ground** (#0b0f14): page and header ground; also the text on filled controls.
- **Panel** (#111820): the readiness container, tab bar, coach panel.
- **Instrument White** (#d9dee5): figures and primary text.
- **Quiet Ink** (#95a0ae): labels, units, baselines, secondary text, and the rail and figure of a row with no band word.
- **Slate Rule** (#2e3d52): every hairline, the limit track, unlit scale steps, and the rail of a no-band-word row.
- **Fault Red** (#ef6a63): failed sync only (header). Stale sync uses the amber warn token, which equals Easy Amber in dark.

The daylight values are in `.impeccable/design.json` and are darkened to hold AA contrast on `#f4f5f7`.

### Named Rules
**The Word Beside the Colour Rule.** Status colour never stands alone. Every coloured rail, figure, chip or step sits next to a spelled-out word (GO-state word, level word, reason text).

**The Server's Words Rule.** The client maps state to colour and compares nothing against a limit. Flagged rows take their reason's colour (stop = rest, caution = easy); a row within its band is go; outside its band but not flagged is hold; a row with no band word (neutral form, no data, no baseline, a guarded ACWR) is plain grey. The READINESS row is the exception: it wears the readiness level's tone (poor/low = rest, moderate = easy, high/prime = go) and shows the level word as its status.

## Typography

**Display, Body and Label Font:** the platform sans stack (Tailwind default `ui-sans-serif, system-ui, sans-serif`). No web fonts are loaded.

**Character:** plain and instrumental. Size and weight do the ranking; the figure is the biggest thing on the row.

### Hierarchy
- **Level word** (600, 1.5rem / text-2xl, line-height 1, 0.12em tracking): the readiness word, tone-coloured, in caps as sent by the server.
- **Figure** (600, 2.25rem / text-4xl, line-height 1, tight tracking): each condition's current value, status-coloured; its unit follows in **Unit** (400, 0.875rem, Quiet Ink).
- **Body** (400, 0.875rem / text-sm): tables, plan, week, chips, buttons.
- **Label** (500 to 600, 0.75rem / text-xs, uppercase, wider tracking): section titles, row headers, status words. This is the floor; nothing is smaller than text-xs.

### Named Rules
**The Tabular Rule.** Numbers are tabular (`tabular-nums`) on the board, header and plan so columns and refetches do not jitter.

**The Twelve Pixel Floor Rule.** The smallest type is text-xs (0.75rem). Uppercase tracked type is for labels and status words, not for decorative lead-ins.

## Layout

One scrolling column inside the shell: header, tab bar, then `main`. At xl (1280px) Today splits into the board (flex, `max-w-5xl` content) and a fixed 32rem coach panel with a left rule; below xl the coach is a toggled full-width view. Bands use `px-6` and `py-5` with a 1px bottom rule; rows use `py-3`. Spacing steps in use: 8, 12, 20, 24px.

The order on Today is fixed: Conditions, Readiness container, HOLD line (only when a review waits), Today's plan, the week.

Responsive: at sm (640px) and up each condition is a table row with columns Condition, Now, 28-day, limit, Status (or Now and 14 days in Trends). Below sm each row becomes a grid of three columns (6rem label, figure, status) with the first line holding label, figure and status, and the baseline and limit marker (or the trend line) on a second line beneath. The column headers stay in the DOM for screen readers (`sr-only`). The limit track shortens from 8rem to 5rem and the sparkline from 10rem to 8rem. The header wraps and its badge and job buttons wrap together; tabs scroll horizontally.

## Elevation & Depth

Flat. There are no shadows. Depth is tonal: Panel (#111820) over Ground (#0b0f14), with 1px Slate Rule hairlines between bands. Emphasis on a row is a 10% Hold Blue wash (active row) and a 2px Hold ring on keyboard focus, never lift.

### Named Rules
**The Flat Board Rule.** Surfaces do not lift. Separate with a rule or a tonal step.

## Shapes

Mostly square bands and rows with small rounding on controls: 6px on buttons and the view toggle, 8px on the readiness container, full pills for reason chips, the review badge and the scale bars. Hairline tracks are 6px tall pills.

## Components

### Condition Row (signature)
A `tr` on sm and up, a three-column grid below. The header cell wears a 4px left border (the row rail) coloured by the row's state, beside the uppercase label; the figure and the status word take the same state colour. Rows are focusable, and hover or focus (also from a reason chip) washes the row 10% Hold Blue. A changed value after a refetch flashes once.

### The Row Rail (deliberate exception)
The 4px left border on the row header cell is a chosen mark (Brian's mockup A). It sits on table cells, not a card, encodes state per row, and always sits beside the status word. Automated detectors report it as a side-tab; that is an accepted exception scoped to condition rows and does not extend to cards, alerts or callouts.

### Limit Marker and Limit Text
A hairline Slate Rule track (6px, pill) with the athlete's band shaded (Quiet Ink at 50%) and a single 2px ink tick at today's value. It is decorative (`aria-hidden`); the limit is always also text beside it ("55–61", "to 8") in text-xs Quiet Ink.

### Sparkline
A 14-day, 1.5px line in the row's state colour with the band shaded (Quiet Ink at 30%) and a dot on today's value. A missing day breaks the line. It is decorative; the figure and status word carry the meaning.

### Readiness Container
The only filled container: Panel ground, Slate Rule border, 8px radius, below the conditions. It holds the tone-coloured level word, a five-step scale (Poor, Low, Moderate, High, Prime; 6px bars with labels; `aria-current` on the lit step), then reason chips. The lit step takes the level's tone (high and prime share go, low and poor share rest, moderate is easy); unlit steps are Slate Rule. No reading shows NO READING in Quiet Ink with no lit step. Chips: stop and caution reasons are buttons that jump to the row (pill, 28px, coloured border and text, spelled reason); info reasons are plain grey text.

### HOLD Line
A single outlined button in Hold Blue ("HOLD · N changes awaiting your approval") that jumps to the review gate. Appears only when a review waits.

### Navigation
A tab bar on Panel ground with a bottom rule. Tabs are text-sm, 40px high; the active tab has a 2px Hold Blue underline and ink text; inactive tabs are Quiet Ink. Scrolls horizontally on narrow screens.

### View Toggle
A two-button segmented control (Figures, Trends), 6px radius, hairline border, 28px high; the pressed state is a Hold 10% wash with ink text.

### Progress Charts
The Progress page reuses the board's rules: each chart is a ruled band (`ChartFrame`: title, one sentence that states the point, controls, then the chart), never a filled card. Charts are hand-rolled SVG on the same tokens. Sport identity comes from five `--sport-*` tokens (swim, bike, run, strength, other), each at least 3:1 against the ground in both themes, and always pairs with a marker shape (circle, square, triangle, diamond, ring) and a written name. Every chart offers "View as table", and stepping through points is a single slider (arrow keys) with a visible readout, so a long history is one tab stop, not one per bar. A partial week is hatched and labelled. The PMC stacks CTL and ATL over a separate TSB panel with a zero line and the neutral-form band, instead of a second axis.

### Motion
One motion: `board-flash`, a 700ms fade from a 22% Hold wash on a value that changed after a refetch. Buttons and links ease colour over 150ms. Under reduced motion the flash is removed and all durations collapse.

## Do's and Don'ts

### Do:
- **Do** put a spelled word beside every status colour.
- **Do** map the server's status words to colour and stop there; the client compares no value against a limit.
- **Do** keep the readiness level below the conditions, and colour the READINESS row by the level.
- **Do** show the limit as text ("55–61", "to 8") whenever a limit marker is drawn.
- **Do** use tabular numerals, text-xs as the minimum size, and the platform sans.
- **Do** separate bands with a 1px Slate Rule and use tonal steps for depth.
- **Do** keep the 4px row rail on condition rows only.
- **Do** keep keyboard focus visible (2px Hold outline) and honour reduced motion.

### Don't:
- **Don't** rely on colour alone to say go, easy, rest or hold.
- **Don't** replace the conditions table with equal-weight metric tiles or rings.
- **Don't** add shadows or lift; the board is flat.
- **Don't** load web fonts or add type below text-xs.
- **Don't** add motion beyond the single refetch flash.
- **Don't** reuse the row rail on cards, alerts or callouts.
