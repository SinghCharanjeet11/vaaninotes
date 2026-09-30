# DESIGN.md

> A quiet paper notebook that happens to have an NPU inside: warm, legible, and honest about what runs where.

Covers two surfaces: the **VaaniNotes app** (`vaani/web/`, tier L1) and the **project landing page** (`docs/index.html`, tier L2).

## 1. Visual Theme & Atmosphere

**Style**: Paper & Ink (derived from the Cream Editorial seed)
**Keywords**: warm paper, ink, saffron, editorial serif, calm, trustworthy, private, multilingual
**Tone**: a well-typeset study notebook — NOT a neon "AI dashboard", NOT glassmorphism, NOT a chatbot
**Feel**: like opening a clean notebook on a wooden desk; the machine stays out of the way and the notes take the page.

**Interaction Tier**: App = L1 (refined static) · Landing page = L2 (fluid interaction)
**Dependencies**: CSS + vanilla JS only. No CDN at runtime in the app (it must work in airplane mode); fonts are self-hosted in `vaani/web/fonts/`.

## 2. Color Palette & Roles

```css
:root {
  /* Backgrounds */
  --bg: #F5F0E6;               /* page: warm paper */
  --surface: #FFFDF8;          /* cards, panels */
  --surface-alt: #EFE8DA;      /* wells, alternate sections, inputs at rest */
  --surface-hover: #FBF6EC;    /* hovered rows / cards */

  /* Borders */
  --border: #DDD4C3;
  --border-hover: #B8AD98;

  /* Text */
  --text: #1C1A17;             /* ink: headings, notes body */
  --text-secondary: #4A453D;   /* descriptions */
  --text-tertiary: #6B6459;    /* labels, timestamps (5.1:1 on --bg) */

  /* Accent */
  --accent: #B93A0E;           /* saffron-rust: primary action, active tab (5.0:1 on --bg) */
  --accent-hover: #9A2F0A;
  --on-accent: #FFFDF8;        /* text on accent (5.7:1) */
  --device: #0F5C5C;           /* "on-device / NPU" status only (6.8:1 on --bg) */

  /* RGB variants for rgba() */
  --bg-rgb: 245, 240, 230;
  --text-rgb: 28, 26, 23;
  --accent-rgb: 185, 58, 14;
  --device-rgb: 15, 92, 92;

  /* Semantic */
  --success: #1F6F43;
  --error: #B42318;
  --warning: #8A5A00;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #15130F;
    --surface: #1E1B16;
    --surface-alt: #26221B;
    --surface-hover: #2C2820;
    --border: #3A352B;
    --border-hover: #5A5344;
    --text: #F3EEE3;
    --text-secondary: #C9C1B2;
    --text-tertiary: #A39B8C;
    --accent: #F08A4B;
    --accent-hover: #F6A36E;
    --on-accent: #1C1A17;
    --device: #6FC7C0;
    --bg-rgb: 21, 19, 15;
    --text-rgb: 243, 238, 227;
    --accent-rgb: 240, 138, 75;
    --device-rgb: 111, 199, 192;
    --success: #6BCB94;
    --error: #FF8A7A;
    --warning: #E5B454;
  }
}
```

**Color Rules:**
- Every colour is referenced through a CSS variable. No hard-coded hex in component CSS or JS.
- `--accent` means "act here" (primary button, active tab, focus ring). One primary action per view.
- `--device` is reserved for hardware truth: the NPU / offline status chips and performance figures. Never decorative.
- Status is never colour-only: every chip pairs colour with an icon and text.

## 3. Typography Rules

**Font Stack:**
```css
/* Landing page (online) */
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600&family=JetBrains+Mono:wght@400;500&display=swap');

/* App (offline): the same families, self-hosted as woff2 via @font-face in vaani/web/fonts/ */
--font-display: "Fraunces", "Iowan Old Style", Georgia, serif;
--font-body: "DM Sans", "Segoe UI Variable", "Segoe UI", "Nirmala UI", "Noto Sans Devanagari", system-ui, sans-serif;
--font-mono: "JetBrains Mono", "Cascadia Mono", Consolas, monospace;
```
"Nirmala UI" (shipped with Windows) renders Devanagari, Bengali, Tamil, Telugu, Gujarati, Kannada, Malayalam and Gurmukhi, so notes in Indian languages never fall back to tofu.

| Role | Font | Size | Weight | Line Height | Letter Spacing |
|------|------|------|--------|-------------|----------------|
| Landing Hero H1 | Fraunces | clamp(2.75rem, 7vw, 5.5rem) | 600 | 1.02 | -0.02em |
| Landing Section H2 | Fraunces | clamp(1.75rem, 3.5vw, 2.75rem) | 600 | 1.1 | -0.01em |
| App page title | Fraunces | 1.375rem | 600 | 1.2 | -0.01em |
| H3 / card title | Fraunces | 1.125rem | 600 | 1.3 | — |
| Body / notes | DM Sans | 0.9375rem (app) · 1.0625rem (landing) | 400 | 1.65 | — |
| Label / eyebrow | DM Sans | 0.75rem | 600 | 1.3 | 0.08em, uppercase |
| Mono (timestamps, metrics) | JetBrains Mono | 0.8125rem | 500 | 1.5 | — |

**Typography Rules:**
- Sizes in `rem`; layout survives 200% zoom.
- Notes and transcript use line-height ≥ 1.65; Indic scripts get `line-height: 1.8`.
- Numbers in metrics use `font-variant-numeric: tabular-nums`.
- Max measure for reading text: 68ch.
- **NEVER use**: Inter, Roboto, Arial as the designed face; Comic/handwriting fonts; all-caps body text.

**Text Decoration:**
- Hero h1: no gradient, no shadow (editorial restraint). One word may take `--accent` as solid colour.
- Section h2: none. Eyebrow labels: uppercase + letter-spacing only.
- Body: never decorated.

## 4. Component Stylings

### Buttons
```css
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 0.5rem;
  min-height: 2.75rem; padding: 0 1.125rem;
  font: 600 0.9375rem/1 var(--font-body);
  border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text); cursor: pointer;
  transition: background-color .15s ease, border-color .15s ease, transform .1s ease;
}
.btn:hover { background: var(--surface-hover); border-color: var(--border-hover); }
.btn:active { transform: translateY(1px); }
.btn:focus-visible { outline: 3px solid rgba(var(--accent-rgb), .45); outline-offset: 2px; }
.btn:disabled, .btn[aria-disabled="true"] { opacity: .5; cursor: not-allowed; transform: none; }

.btn--primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.btn--primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
.btn--primary:disabled { background: var(--accent); }

.btn--record[aria-pressed="true"] { border-color: var(--error); color: var(--error); }
```

### Cards
```css
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 1.25rem; transition: border-color .15s ease, box-shadow .15s ease;
}
.card:hover { border-color: var(--border-hover); }
.card:focus-within { border-color: var(--border-hover); box-shadow: 0 0 0 3px rgba(var(--accent-rgb), .12); }
```

### Navigation / Tabs
```css
.tabs { display: flex; gap: .25rem; border-bottom: 1px solid var(--border); }
.tab {
  min-height: 2.75rem; padding: 0 1rem; background: none; border: 0;
  border-bottom: 2px solid transparent; margin-bottom: -1px;
  font: 600 0.875rem/1 var(--font-body); color: var(--text-tertiary); cursor: pointer;
}
.tab:hover { color: var(--text); }
.tab[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); }
.tab:focus-visible { outline: 3px solid rgba(var(--accent-rgb), .45); outline-offset: -3px; border-radius: 6px; }
.tab:disabled { opacity: .45; cursor: not-allowed; }

/* Landing nav: transparent at top, solid paper after scroll */
.nav { position: sticky; top: 0; transition: background-color .2s ease, border-color .2s ease; border-bottom: 1px solid transparent; }
.nav.is-scrolled { background: rgba(var(--bg-rgb), .94); border-bottom-color: var(--border); }
```

### Links
```css
a { color: var(--accent); text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: var(--accent-hover); text-decoration-thickness: 2px; }
a:focus-visible { outline: 3px solid rgba(var(--accent-rgb), .45); outline-offset: 2px; border-radius: 3px; }
```

### Tags / Status chips
```css
.chip {
  display: inline-flex; align-items: center; gap: .375rem;
  padding: .25rem .625rem; border-radius: 999px;
  font: 600 0.75rem/1.3 var(--font-body);
  background: var(--surface-alt); color: var(--text-secondary); border: 1px solid var(--border);
}
.chip--device { color: var(--device); border-color: rgba(var(--device-rgb), .35); background: rgba(var(--device-rgb), .08); }
.chip--warn { color: var(--warning); }
```

### Form controls
```css
.field label { display: block; margin-bottom: .375rem; font: 600 0.8125rem/1.3 var(--font-body); color: var(--text-secondary); }
.select, .input {
  width: 100%; min-height: 2.75rem; padding: 0 .75rem;
  font: 400 0.9375rem/1.4 var(--font-body); color: var(--text);
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
}
.select:hover, .input:hover { border-color: var(--border-hover); }
.select:focus-visible, .input:focus-visible { outline: 3px solid rgba(var(--accent-rgb), .45); outline-offset: 1px; border-color: var(--accent); }
.select:disabled, .input:disabled { opacity: .5; cursor: not-allowed; }
.check { display: flex; align-items: center; gap: .5rem; min-height: 2.75rem; }
.check input { width: 1.125rem; height: 1.125rem; accent-color: var(--accent); }
```

### Dropzone
```css
.dropzone { border: 1.5px dashed var(--border-hover); border-radius: 14px; background: var(--surface-alt); padding: 1.5rem; text-align: center; }
.dropzone:hover, .dropzone.is-dragover { border-color: var(--accent); background: var(--surface-hover); }
.dropzone:focus-within { outline: 3px solid rgba(var(--accent-rgb), .45); outline-offset: 2px; }
```

### Flashcard (flip)
```css
.flashcard { perspective: 900px; min-height: 9rem; background: none; border: 0; padding: 0; cursor: pointer; text-align: left; }
.flashcard__inner { position: relative; height: 100%; min-height: 9rem; transition: transform .45s cubic-bezier(.2,.7,.2,1); transform-style: preserve-3d; }
.flashcard[aria-pressed="true"] .flashcard__inner { transform: rotateY(180deg); }
.flashcard__face { position: absolute; inset: 0; backface-visibility: hidden; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); padding: 1rem; }
.flashcard__face--back { transform: rotateY(180deg); background: var(--surface-alt); }
.flashcard:hover .flashcard__face { border-color: var(--border-hover); }
.flashcard:focus-visible { outline: 3px solid rgba(var(--accent-rgb), .45); outline-offset: 3px; border-radius: 14px; }
```

### Progress
```css
.progress { height: 6px; border-radius: 999px; background: var(--surface-alt); overflow: hidden; }
.progress__bar { height: 100%; background: var(--accent); border-radius: inherit; transition: width .3s ease; }
```

## 5. Layout Principles

**Container:**
- App: max width 1240px, padding 1.5rem (1rem on mobile)
- Landing: max width 1120px; narrow text variant 680px

**Spacing Scale:** 4 / 8 / 12 / 16 / 24 / 32 / 48 / 72 / 112 px
- Landing section padding: 112px desktop, 72px mobile
- Component gap: 16–24px · Card internal padding: 20px

**Grid:**
```css
.app-grid { display: grid; grid-template-columns: minmax(300px, 380px) minmax(0, 1fr); gap: 1.5rem; align-items: start; }
.bento { display: grid; grid-template-columns: repeat(6, 1fr); gap: 1rem; }   /* landing features: unequal spans */
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: .75rem; }
```

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Flat | 1px `--border`, no shadow | panels, cards at rest, inputs |
| Subtle | `0 1px 2px rgba(var(--text-rgb), .06)` | sticky header, primary button |
| Elevated | `0 12px 32px -12px rgba(var(--text-rgb), .22)` | landing hero "notebook" mock, toasts |
| Focus | `0 0 0 3px rgba(var(--accent-rgb), .45)` | keyboard focus on any control |

Paper is flat: separation comes from borders and tone steps (`--bg` → `--surface` → `--surface-alt`), not from stacked shadows.

## 7. Animation & Interaction

**Motion Philosophy**: ink settling on paper — short, opacity + transform only, never blocking the task.
**Tier**: App L1 · Landing L2

### Dependencies
None. CSS keyframes + `IntersectionObserver`.

### Entrance Animation
```css
@keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
.rise { animation: rise .35s cubic-bezier(.2,.7,.2,1) both; }
.rise:nth-child(2) { animation-delay: .05s; } .rise:nth-child(3) { animation-delay: .1s; }
```

### Scroll Behavior (landing only)
```js
const io = new IntersectionObserver((entries) => entries.forEach(e => {
  if (e.isIntersecting) { e.target.classList.add('is-visible'); io.unobserve(e.target); }
}), { threshold: 0.15 });
document.querySelectorAll('.reveal').forEach(el => io.observe(el));
addEventListener('scroll', () => nav.classList.toggle('is-scrolled', scrollY > 24), { passive: true });
```
```css
.reveal { opacity: 0; transform: translateY(18px); transition: opacity .6s ease, transform .6s cubic-bezier(.2,.7,.2,1); }
.reveal.is-visible { opacity: 1; transform: none; }
```

### Signature motion (landing, six required classes)
| Class | Effect | Where |
|---|---|---|
| Text — H1 | word-by-word mask reveal (`clip-path`) on load | hero title |
| Text — H2 | per-line rise on scroll (`.reveal`) | every section title |
| Text — body/label | typed transcript line → notes (TextType) | hero notebook mock |
| Element | pointer spotlight via `--mx/--my`, rAF-throttled | bento cards |
| Component | unequal bento grid + flip flashcards | features / demo |
| Background | slow drifting ink-wash gradient (transform only) | hero |

Three "wow" points: (1) hero notebook that writes itself from a live waveform, (2) first scroll: full-width marquee of the phrase in eleven Indian scripts, (3) bento features with spotlight. One small delight: the airplane-mode chip — toggling it proves the page makes no network calls.

### Hover & Focus States
All interactive elements define `:hover` and `:focus-visible` (section 4). Focus ring is always 3px `--accent` at 45%.

### App-specific feedback
- Recording: button shows elapsed time + a level meter (transform: scaleX), not a pulsing glow.
- Processing: determinate progress bar with a text status in an `aria-live="polite"` region.
- Results appear section by section with `.rise` as the NPU produces them.

### Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; scroll-behavior: auto !important; }
  .reveal { opacity: 1; transform: none; }
  .flashcard__inner { transition: none; }
}
```

## 8. Do's and Don'ts

### Do
- Show where computation runs (NPU / CPU) and that nothing leaves the device, in plain words.
- Keep one primary action per view: "Generate notes".
- Label every control with visible text; pair every status colour with an icon and words.
- Keep all targets ≥ 44×44px and all text ≥ 4.5:1 contrast.
- Render notes as real headings, lists and paragraphs so screen readers can navigate them.
- Set the `lang` attribute on generated content so Indic scripts get the right voice and font.
- Prefer borders and tone steps over shadows.

### Don't
- ❌ No purple/blue "AI" gradients, no glassmorphism, no glow.
- ❌ No emoji as icons — inline SVG only.
- ❌ No hard-coded hex colours outside the `:root` token block.
- ❌ No external requests from the app UI (no CDN fonts, scripts, analytics). CSP enforces `default-src 'self'`.
- ❌ No `filter: blur()` on moving elements; no scroll-jacking; no custom cursor.
- ❌ No spinner-only waiting states — always say what is happening and how far along it is.
- ❌ No colour-only status, no placeholder-as-label, no removed focus outlines.
- ❌ No layout that needs horizontal scrolling at 360px.
- ❌ No Qualcomm / Snapdragon logos or brand colours presented as the app's own identity.
- ❌ No fabricated benchmark numbers: performance tiles show measured values or cite Qualcomm AI Hub.

## 9. Responsive Behavior

**Breakpoints:**
| Name | Width | Key Changes |
|------|-------|-------------|
| Desktop | > 960px | App: two columns (capture · results). Landing: 6-col bento |
| Tablet | 600–960px | App: single column, capture panel first. Bento: 2 columns |
| Mobile | < 600px | Single column, tabs scroll horizontally, 1rem gutters, stacked metrics |

**Touch Targets:** minimum 44×44px
**Collapsing Strategy:** capture panel stacks above results; tab list becomes horizontally scrollable (`overflow-x: auto`); landing nav links collapse to the primary CTA only.

```css
@media (max-width: 960px) { .app-grid { grid-template-columns: 1fr; } .bento { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .bento { grid-template-columns: 1fr; } .tabs { overflow-x: auto; } .container { padding-inline: 1rem; } }
```
