# Trade23 UI Foundation

The desktop and web presentation share these tokens:

| Token | Value |
| --- | --- |
| Background | `#111214` |
| Surface | `#191c1f` |
| Raised controls | `#24282c` |
| Border | `#343b40` |
| Text | `#edf1f4` |
| Muted | `#a0aab2` |
| Accent | `#59dcb2` |
| Profit | `#47c997` |
| Loss | `#ff777d` |

The brand source is `assets/trade23-mark.svg`. Native PNG sizes and the
multi-resolution ICO are committed, so normal builds need no image renderer.
`scripts/build_ui_assets.mjs` can regenerate the PNG/Lucide variants after
`npm ci` in `web`; provide an installed `sharp` module with `SHARP_MODULE` if
it is not on the script's module path. ICO output is a format conversion of
the 256px PNG. Never use the generic Tk/Vite icons as the product identity.

Desktop uses Segoe UI (Helvetica fallback), tabular monetary figures, flat
sections, guarded destructive actions, hover/focus help and scrollable tables.
Its starting window is bounded to the current display. Settings scroll even
when the pointer is over a field. The live strategy/accounting is unchanged.

Web uses system fonts, 44px touch controls, visible keyboard focus and reduced
motion support. At 720px and below, navigation sits at the bottom with safe-area
padding and trades become stacked rows. Settings remain a read-only snapshot;
the redesign does not add public control endpoints or store login credentials.

The local `/about` page is a website foundation using actual UI screenshots of
a disposable offline account, clearly captioned. It is not a deployed site,
evidence of live execution or a performance claim. Regenerate preview images
only with test data; never publish a screenshot of private balances/history.

Verification: `python -m tests.smoke_dashboard` checks three desktop sizes,
icon resources and reachable settings. Web smoke checks cover sign-in,
overview, history, settings and the product preview at desktop/tablet/phone
widths. Playwright artifacts are ignored under `output/playwright`.
