---
name: ScopePay
description: A purchase document with a contextual approval and payment rail.
colors:
  ink: "#182d3d"
  muted: "#526577"
  canvas: "#f3f6f8"
  surface: "#ffffff"
  line: "#dbe3e9"
  navigation: "#172e3f"
  primary: "#086657"
  primary-hover: "#064d42"
  primary-soft: "#e4f3ee"
  warning: "#80520c"
  warning-bg: "#fff3d9"
  danger: "#a52d37"
  danger-bg: "#fcecee"
  focus: "#2369b8"
typography:
  body:
    fontFamily: "Segoe UI, Microsoft YaHei, system-ui, sans-serif"
    fontSize: "16px"
    lineHeight: 1.5
  heading:
    fontSize: "1.8rem"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.025em"
  section:
    fontSize: "1.15rem"
    fontWeight: 650
    lineHeight: 1.4
  label:
    fontSize: "0.8125rem"
    fontWeight: 600
rounded:
  control: "6px"
  surface: "10px"
spacing:
  compact: "8px"
  control: "12px"
  group: "20px"
  section: "24px"
  document: "28px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "44px minimum"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
---

# Design System: ScopePay

## Overview

A private purchase register and document review surface. Precision comes from aligned money columns, persistent original wording and one contextual main action. The application opens directly into purchases. State labels, rather than explanatory feature cards, communicate what can happen next.

## Colors

Cool neutral document surfaces and a dark slate navigation rail support daytime desk use. Dark teal identifies primary actions and completed states. Amber is reserved for waiting/unknown states; red marks validation or explicit rejection. Unknown settlement is never colored as a failed payment. Source and user-entered prose retain their original language.

## Typography

One offline system family supports Chinese and English. Headers use fixed rem sizes, not viewport-scaled marketing type. Table text is 0.875rem, supporting metadata 0.75rem; narrow table metadata is 0.6875rem and remains supplementary. Financial values use tabular numerals. Monospace is restricted to receipt/order identifiers.

## Layout

The desktop shell is a 208px sidebar and a flexible work area. Main content has 40px inset and a 1600px maximum. Editors/details use a flexible document with a 320px action rail, 24px apart. At 1160px navigation/insets compress; at 960px document and rail stack; at 700px navigation becomes a compact top row and table rows become stacked records. Unknown payment puts its recovery rail before the document on narrow screens. Activity remains after the actionable content.

## Elevation & Depth

Flat surfaces use one border rather than decorative shadows. A native dialog backdrop is the sole overlay for consequential return/revoke decisions. No page entrance animation or external imagery is used.

## Shapes

Six-pixel controls, ten-pixel document surfaces and five-pixel status labels. The logo and UI icons are authored geometric SVG in a consistent stroke. There are no decorative raster assets or icon-font dependencies.

## Components

Primary buttons name the next action and, for capture, the exact currency/amount. Secondary actions remain adjacent. During a mutation, navigation/language controls and task buttons are disabled; persisted state is reread before enabling the next action. Keyboard focus uses a three-pixel blue ring with three-pixel offset. Inputs have persistent labels, local errors and an error summary; native date/time controls keep platform behavior.

The approval rail pairs the immutable total with budget headroom. Original source and order identifiers are progressively disclosed. The register supports search, state filter, paging and explicit draft recovery. A receipt is a document, with export and print actions, not a success animation.

## Do's and Don'ts

- Do keep domain labels bilingual while preserving user text and evidence.
- Do show a single amount basis and explicit simulation/Sandbox mode.
- Do place recovery before any new side effect when settlement is unknown.
- Do keep every input/action reachable without hover.
- Don't use display fonts, gradients, decorative metric cards, or technical checklists in the product UI.
- Don't call a local reviewer name an authenticated customer signature or a simulated receipt a real payment.
