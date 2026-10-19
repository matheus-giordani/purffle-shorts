---
name: PurffleShorts Studio
description: A compact studio for making short videos and following their resource use.
colors:
  bg: "#0b0c10"
  bg2: "#101218"
  panel: "#14161d"
  panel2: "#1a1d26"
  line: "#252834"
  line2: "#303443"
  text: "#eceef4"
  muted: "#8e93a6"
  faint: "#5d6274"
  accent: "#ffe11a"
  accent-ink: "#15161b"
  accent-soft: "rgba(255, 225, 26, .12)"
  violet: "#8b5cf6"
  blue: "#5b9dff"
  ok: "#34d399"
  bad: "#fb7185"
  ok-soft: "rgba(52, 211, 153, .13)"
  bad-soft: "rgba(251, 113, 133, .13)"
  blue-soft: "rgba(91, 157, 255, .14)"
  bg-light: "#f5f6fa"
  bg2-light: "#eef0f5"
  panel-light: "#ffffff"
  panel2-light: "#f7f8fb"
  line-light: "#e3e6ee"
  line2-light: "#d4d8e3"
  text-light: "#151821"
  muted-light: "#5d6275"
  faint-light: "#9095a6"
  accent-light: "#f5c400"
  accent-soft-light: "rgba(245, 196, 0, .16)"
  ok-light: "#0f9f6e"
  bad-light: "#d23a57"
  blue-light: "#2d6ae0"
  violet-light: "#6d3fe0"
typography:
  body:
    fontFamily: '"Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
    fontSize: "14.5px"
    lineHeight: 1.5
  page-title:
    fontSize: "24px"
    letterSpacing: "-.02em"
  section-label:
    fontSize: "13px"
    fontWeight: 650
    letterSpacing: ".06em"
  field-label:
    fontSize: "12.5px"
    fontWeight: 600
  cost-value:
    fontSize: "20px"
    fontWeight: 650
  button:
    fontSize: "14.5px"
    fontWeight: 650
    lineHeight: 1.5
  mono:
    fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace'
    fontSize: "12.5px"
rounded:
  r: "14px"
  r-sm: "10px"
  pill: "999px"
spacing:
  "6": "6px"
  "8": "8px"
  "10": "10px"
  "12": "12px"
  "16": "16px"
  "18": "18px"
  "20": "20px"
  "22": "22px"
  "24": "24px"
  "32": "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.r-sm}"
    typography: "{typography.button}"
    padding: "10px 16px"
  button-secondary:
    backgroundColor: "{colors.panel2}"
    textColor: "{colors.text}"
    rounded: "{rounded.r-sm}"
    typography: "{typography.button}"
    padding: "10px 16px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.r-sm}"
    typography: "{typography.button}"
    padding: "7px 10px"
  button-danger:
    backgroundColor: "{colors.panel2}"
    textColor: "{colors.bad}"
    rounded: "{rounded.r-sm}"
    typography: "{typography.button}"
    padding: "10px 16px"
  field:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.r-sm}"
    padding: "9px 11px"
    width: "100%"
  card:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.r}"
    padding: "18px"
  nav-active:
    backgroundColor: "{colors.panel2}"
    textColor: "{colors.text}"
    rounded: "{rounded.r-sm}"
    padding: "9px 12px"
  chip:
    backgroundColor: "{colors.panel2}"
    textColor: "{colors.muted}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  chip-confirmed:
    backgroundColor: "{colors.ok-soft}"
    textColor: "{colors.ok}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  chip-estimated:
    backgroundColor: "{colors.blue-soft}"
    textColor: "{colors.blue}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  speed-range:
    width: "100%"
---

# Design System: PurffleShorts Studio

## Overview

**Creative North Star: "From draft to finished video"**

The Studio is a compact production workspace. Neutral surfaces hold forms, previews, jobs and recorded usage; yellow identifies the brand, primary actions and active progress. New features extend the existing components and spacing rather than introducing a separate visual language.

The Costs extension follows model calls through drafts, executions and finished outputs. It keeps confirmed charges, estimates and missing information visible while allowing progressively deeper inspection. This document extracts the implemented system; it does not introduce a new identity or an additional theme.

**Key Characteristics:**

- Yellow accent with neutral panels and thin dividers.
- Compact sans serif typography with tabular figures for money, counts and timing.
- Rounded controls, restrained elevation and native form behavior.
- Text labels distinguish financial confidence and incomplete telemetry.

Sources: [shell and navigation](purffle_shorts/web/index.html#L14), [shared styles](purffle_shorts/web/app.css#L2), [Costs composition](purffle_shorts/web/costs.js#L58). The frontmatter mirrors existing CSS values. Color keys ending in `-light` describe media-query overrides of the corresponding CSS variable; numeric spacing keys record reused literal values, not new CSS variables.

## Colors

Dark is the default palette; the system's light preference overrides the same CSS variables. Preserve both assignments when extending a surface.

### Primary

- **Studio yellow** (`accent`, `accent-soft`, `accent-ink`): logo, primary buttons, range controls, focus treatment, budget progress and confirmed chart bars. The soft background supports selected choices and notices; dark ink supplies primary-button text.

### Secondary

- **Information blue** (`blue`, `blue-soft`): informational states and estimated charges. Daily charts separate blue estimates from yellow confirmed charges.
- **Success green** (`ok`, `ok-soft`): successful states and confirmed or explicitly free cost badges.
- **Error rose** (`bad`, `bad-soft`): failures, error badges and destructive action text.
- **Feature violet** (`violet`): the existing new-format marker.

### Neutral

- **Canvas and shell** (`bg`, `bg2`): page background, recessed fields and navigation shell.
- **Panels** (`panel`, `panel2`): cards, selected navigation and secondary controls.
- **Dividers** (`line`, `line2`): surface edges, table rows and selected-control strokes.
- **Text** (`text`, `muted`, `faint`): main content, supporting labels and the existing quieter hints. Costs-page and video-cost hints explicitly use `muted` for readability in both themes.

**The Explicit State Rule.** Show the cost information label alongside the amount. Missing prices remain “Not reported” or counted as unpriced calls; they must not appear as a zero charge.

Sources: [palette and light overrides](purffle_shorts/web/app.css#L2), [chips](purffle_shorts/web/app.css#L108), [chart colors](purffle_shorts/web/app.css#L156), [scoped hint contrast](purffle_shorts/web/app.css#L378), [cost labels and money](purffle_shorts/web/costs.js#L6).

## Typography

**Body and interface font:** Inter followed by the system sans serif stack. No webfont is loaded by the HTML shell, so the installed or system fallback is part of the current behavior.

**Mono font:** the system monospace stack for identifiers, paths, logs and code. Impact/Anton/Arial Black appears inside caption-style previews; it is not interface typography.

The hierarchy stays compact: page titles use `page-title`; uppercase card headings use `section-label`; field labels use `field-label`. Cost summary figures use `cost-value` and tabular numerals, reducing to (17px) below (600px); drawer totals also use (17px). Cost table content uses (13px), secondary resource lines (11px), and currency approximations (12px).

Sources: [base typography](purffle_shorts/web/app.css#L10), [titles and fields](purffle_shorts/web/app.css#L52), [cost typography](purffle_shorts/web/app.css#L134), [caption previews](purffle_shorts/web/app.css#L225).

## Layout

Desktop uses a fixed-width navigation column (236px) and a flexible main region, with main padding (26px 32px 60px). Cards use `spacing.18`, form grids use `spacing.12`, action groups use `spacing.8`, and the Create workspace uses two columns separated by `spacing.20`.

The current Costs composition is: header and actions → filters → four-part summary → monthly budgets → daily chart → breakdown tabs → collapsed settings. The summary is a definition list bounded by dividers, rather than a separate row of cards. Models, Videos and Calls & runs share one ledger container; the latter exposes Calls and Executions. This order belongs to the Costs surface, not every Studio page.

| Maximum viewport width | Implemented change |
| --- | --- |
| 1150px | Cost date filters become two columns; extra filters become three. Budget/price settings become two columns. |
| 1100px | Create becomes one column; its sticky section becomes static. General KPI grids become two columns. |
| 860px | Navigation becomes a sticky, horizontally scrollable icon row; brand text and footer disappear. Main padding becomes (18px 16px 60px), drawers become one column and action rows stack. |
| 600px | Cost summary and extra filters use two columns. Budget tracks, detailed totals and settings fields stack. |
| 480px | General form grids stack; caption swatches and Library thumbnails use two columns. |

Cost tables preserve a minimum width (650px) inside a horizontal scrolling region. Long identifiers wrap within cells; resource quantities occupy separate lines. The chart also scrolls horizontally when its per-day minimum widths exceed available space.

Sources: [shell](purffle_shorts/web/app.css#L32), [Costs layout](purffle_shorts/web/app.css#L126), [Costs breakpoints](purffle_shorts/web/app.css#L192), [Create layout](purffle_shorts/web/app.css#L208), [shared breakpoints](purffle_shorts/web/app.css#L358), [resource lines](purffle_shorts/web/app.css#L377).

## Elevation & Depth

Cards are flat, separated by neutral fills and single-pixel borders. Inset strokes define secondary buttons and selected navigation. The existing `--shadow` is reserved for the phone preview, video drawer and toasts; its dark and light values are carried in the sidecar. The drawer adds a dimmed, lightly blurred backdrop and sits above the shell; toasts sit above the drawer.

Motion communicates state: buttons move down (1px) when pressed, Library cards lift (2px) on hover, running stages slide and toasts enter briefly. The reduced-motion preference removes animations and transitions throughout the interface. Preserve that override when adding motion.

Sources: [button states](purffle_shorts/web/app.css#L79), [preview and progress](purffle_shorts/web/app.css#L261), [Library hover](purffle_shorts/web/app.css#L281), [drawer](purffle_shorts/web/app.css#L296), [toasts and reduced motion](purffle_shorts/web/app.css#L350).

## Shapes

Use `rounded.r` for shared cards and `rounded.r-sm` for fields, buttons and navigation. Pills are reserved for badges, chips and switch tracks. Existing local details include segmented containers (11px), their selected buttons (8px), cost price groups and scenes (12px), and chart/budget details (4px). Icons use thin rounded strokes; filled play artwork is the brand mark. Caption preview treatments and the phone frame remain content previews rather than a new shape system.

Sources: [radii and icons](purffle_shorts/web/app.css#L9), [segmented controls](purffle_shorts/web/app.css#L94), [chips](purffle_shorts/web/app.css#L108), [price groups](purffle_shorts/web/app.css#L182).

## Components

### Buttons and navigation

Primary actions use yellow with dark ink. Secondary actions use the raised neutral panel and an inset stroke; ghost actions use muted text and gain a neutral fill on hover; danger actions retain the secondary shape with error-colored text. Shared buttons brighten on hover and translate on press; disabled buttons reduce opacity and use the disabled cursor. Compact actions use (6px 11px) padding and (13px) type.

Active navigation uses a neutral fill, inset stroke and yellow icon. Segmented controls use real buttons with `aria-pressed` to communicate the selected option. Route changes focus the main region without scrolling it before resetting the page position.

Sources: [button and navigation styles](purffle_shorts/web/app.css#L40), [button variants](purffle_shorts/web/app.css#L79), [segmented controls](purffle_shorts/web/app.css#L94), [routing focus](purffle_shorts/web/app.js#L166).

### Cards and fields

Shared cards use a neutral panel, one-pixel divider border and `spacing.18` padding. Text fields, selects and textareas use recessed canvas fills; focus changes the border to yellow and adds a soft (3px) ring. Labels, helper copy and native range controls are retained. Cost date inputs use the second panel tone and the browser's light/dark control rendering.

Sources: [cards and fields](purffle_shorts/web/app.css#L58), [cost date inputs](purffle_shorts/web/app.css#L132).

### Costs and resources

Keep **Confirmed**, **Estimated**, **Pending**, **Not reported** and **No API charge** as distinct textual states. Confirmed and free badges use success treatment; estimates use blue; pending and unknown remain neutral. USD is primary. Optional BRL appears on a second line with an approximation sign, with the configured rate and update date explained beneath the summary.

The daily chart stacks confirmed and estimated spend, includes a text legend, and exposes each day as a labeled button that filters calls. “Daily values” provides a table alternative. Ledger headers use semantic scopes; details drill into model, execution or output records. Monthly budget rows pair written amounts and percentages with labeled progress elements. Alerts occur at (80%) and (100%); the interface explains that budgets do not interrupt generation.

Per-video details show direct, shared and known totals, allocated resources, stored artifact sizes, execution timing, stage breakdowns and individual calls. They retain explicit messages for unpriced calls, incomplete telemetry, reused drafts, deleted files and videos predating tracking. Refreshing data preserves focus when a focused control is replaced and focus has fallen to the document body. Loading, empty and error states use real text; summaries and ledgers announce updates politely, and load errors use an alert region.

Sources: [money and status helpers](purffle_shorts/web/costs.js#L6), [focus restoration](purffle_shorts/web/costs.js#L23), [summary and budget rows](purffle_shorts/web/costs.js#L154), [tables and resources](purffle_shorts/web/costs.js#L218), [daily chart](purffle_shorts/web/costs.js#L261), [settings](purffle_shorts/web/costs.js#L277), [video detail](purffle_shorts/web/costs.js#L305).

### Video drawer

The right-hand modal drawer uses the existing neutral shell, a width capped at (860px), an independently scrolling panel and a backdrop. Video and metadata form two columns on desktop; costs-only content spans the panel. Opening focuses the close button, makes the underlying app inert and locks page scrolling. Tab navigation stays within visible enabled controls; Escape or the backdrop closes the drawer. Closing pauses video and restores focus to the original control, its replacement or the main region.

Sources: [dialog semantics](purffle_shorts/web/index.html#L35), [drawer styling](purffle_shorts/web/app.css#L296), [keyboard handling](purffle_shorts/web/app.js#L137), [open and close lifecycle](purffle_shorts/web/app.js#L647).

### Final video speed

Create and Clip reuse the native range pattern: visible “Final video speed” label, values from (0.5×) to (2×), increments of (0.05×), yellow control accent and a tabular numeric output. Both link the range to its helper copy with `aria-describedby`. Create updates the approximate exported duration from narration length divided by speed. Clip explains when the speed is applied. The helper text explains preserved audio pitch and synchronized captions; persisted settings and re-render defaults retain the selected speed.

Sources: [range styling](purffle_shorts/web/app.css#L75), [Create control](purffle_shorts/web/app.js#L320), [live output update](purffle_shorts/web/app.js#L399), [re-render default](purffle_shorts/web/app.js#L636), [Clip control](purffle_shorts/web/app.js#L771).

## Do's and Don'ts

### Do:

- Do extend the existing yellow accent, neutral panels, typography and component dimensions.
- Do preserve dark and system-selected light assignments together.
- Do show confidence, missing prices and incomplete tracking in text beside financial figures.
- Do keep long resource values readable through line breaks, cell wrapping and contained horizontal scrolling.
- Do preserve labels, keyboard operation, focus restoration, modal isolation and reduced-motion behavior.

### Don't:

- Don't display an unreported price as a confirmed zero charge.
- Don't merge estimates or approximate BRL conversions into confirmed USD figures.
- Don't introduce a separate color, font, card or spacing system for Costs or speed controls.
- Don't let a background refresh discard a user's focus or make the underlying app interactive while its modal drawer is open.
