# LGHS Fleet Art Direction

## Identity motif: Signal Field

LGHS Fleet should have memorable visual identity without turning operational screens into marketing pages. The motif is a low-resolution **signal field**: a loose raster network of small square nodes, sparse links, concentric controller rings and a handful of moving packets.

It is intentionally not a globe and not a copy of Cloudflare's earth/pixel work. Its meaning is specific to LGHS: many classroom devices, one controller plane, encrypted communications moving through the field.

## Where art belongs

Use:

- Cloudflare Access/session boundary and authentication failure states;
- restrained overview masthead;
- empty/onboarding states;
- provisioning flow illustrations later;
- release/update completion moments where a small motion cue helps orientation.

Do not use:

- behind fleet tables;
- behind alerts, sudo approvals or destructive confirmations;
- as a full-screen permanent moving background;
- as decorative noise around every card.

## Animation personality

- precise, technical, calm;
- packets move in deliberate paths rather than random particle swarms;
- no bounce, confetti or floating gradients;
- transitions communicate containment and hierarchy;
- healthy status does not pulse forever;
- warning/critical states are visually stable so users can read them.

## Implementation rules

The first Signal Field implementation is Canvas 2D because it is tiny, dependency-free and easy to pause. It runs through `requestAnimationFrame`, caps decorative drawing to 30 fps, stops when the tab is hidden, respects reduced motion, and caps DPR at 2.

For more complex future art, prefer SVG for bounded illustrations and OffscreenCanvas/worker rendering for expensive procedural backgrounds. Do not introduce WebGL/Three.js just to make a login page look impressive.

## Color

Art pulls from the same semantic/design tokens as the application, but at low alpha. One warm signal color may be used as the brand spark; semantic red/amber/green remain reserved for operational meaning.

## Accessibility

Decorative art is `aria-hidden`. It never contains the only representation of state. Motion is removable. Any data visualization has a textual/table alternative and never depends on color alone.
