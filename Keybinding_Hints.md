# Keybinding Hints: How to Surface Actions to the User

This guide explains the mechanisms lazygit uses to tell the user which keys do
what, and how a developer adds or modifies those hints. It describes the
system, not any particular spoken language: every user-facing string flows
through the translation layer, so the same steps apply regardless of the
language the end user has configured.

## Where hints actually appear

Users discover keybindings through three surfaces, all driven from the same
`Binding` struct — there is one source of truth per keybinding.

1. **Bottom options bar** — the `description: key | description: key | …` line
   at the bottom of the screen, rebuilt on every render. Space is limited, so
   only bindings explicitly flagged appear here, and the line is truncated
   with an ellipsis when it overflows.
   - Renderer: `pkg/gui/options_map.go` (`OptionsMapMgr.renderContextOptionsMap`).
   - Triggered from `pkg/gui/layout.go` on each layout pass.
   - Written into the `Options` view (`pkg/gui/views.go`).

2. **Keybindings menu** — the popup opened with `?` (the `Universal.OptionMenu`
   key). Lists *every* binding that has a description, grouped into Local,
   Global, and Navigation sections. Selecting a row shows its tooltip in a
   panel below the menu.
   - Built by `pkg/gui/controllers/options_menu_action.go`
     (`OptionsMenuAction.Call` and `getBindings`).
   - Menu rendering and `@`-prefix key filtering: `pkg/gui/context/menu_context.go`.
   - Tooltip panel content: `pkg/gui/controllers/menu_controller.go` writes the
     selected item's tooltip into the `Tooltip` view.

3. **Cheatsheet docs** — per-language Markdown tables under
   `docs-master/keybindings/Keybindings_<lang>.md`, one section per view. These
   are auto-generated and checked into the repo; CI fails if they are stale.
   - Generator: `pkg/cheatsheet/generate.go` (entry point
     `pkg/cheatsheet/generator.go`, run via `go generate ./...`, i.e.
     `just generate`).
   - Columns: `| Key | Action | Info |`, where *Key* is the key label(s),
     *Action* is the binding description (plus any `Alternative`), and *Info*
     is the `Tooltip` with newlines rendered as `<br>`.

## The `Binding` struct — the single source of truth

Defined in `pkg/gui/types/keybindings.go`. The fields that control *what the
user sees* are:

| Field | Used by | Purpose |
|---|---|---|
| `Keys` | all three surfaces | The key(s) that trigger the action. The first key is what shows in the options bar and menu. |
| `Description` | menu + cheatsheet | Long-form label. **Required** for a binding to appear in the menu or cheatsheet; the cheatsheet generator reads this field directly (not `DescriptionFunc`). |
| `DescriptionFunc` | menu only | Dynamic replacement for `Description`. Must stay cheap. You still must set `Description` with a generic value for the cheatsheet. |
| `ShortDescription` | options bar | Compact label for the bottom bar. When unset, the bar falls back to `GetDescription()`. |
| `ShortDescriptionFunc` | options bar | Dynamic replacement for `ShortDescription`. |
| `Tooltip` | menu + cheatsheet "Info" column | Multi-line help shown when the binding's row is highlighted in the menu. |
| `Alternative` | cheatsheet only | Free-text hint for an alternate key, shown in parens after the action name (e.g. `fn+up/shift+k`). |
| `Tag` | cheatsheet + menu grouping | `"navigation"` groups a binding under Navigation; `"global"` under Global. Otherwise grouping follows `ViewName`. |
| `DisplayOnScreen` | options bar | If `true` (and the binding is not currently disabled), the binding is eligible to appear in the bottom bar. |
| `DisplayStyle` | options bar only | Optional `*style.TextStyle` to color the hint on the bottom bar. |
| `GetDisabledReason` | all three surfaces | Returns a `*DisabledReason` (`Text`, `ShowErrorInPanel`, …) when the action is currently unavailable. Disabled bindings are *hidden* from the options bar (no strikethrough — space is too tight) and shown with a `Disabled: …` prefix in the menu tooltip. |

Resolution helpers on `Binding`:

- `GetDescription()` → `DescriptionFunc()` if set, else `Description`.
- `GetShortDescription()` → `ShortDescriptionFunc()` if set, else
  `ShortDescription`, else `GetDescription()`.
- `IsDisabled()` → `GetDisabledReason` is set and returns non-nil.

## How a binding reaches the user

There is no manual registration of individual bindings. The flow is:

1. **A controller returns bindings from `GetKeybindings(opts)`.** One
   `[]*types.Binding` per controller. See e.g.
   `pkg/gui/controllers/files_controller.go:42`.
2. **`AttachControllers`** (`pkg/gui/controllers/attach.go`) registers each
   controller's `GetKeybindings` onto its context via `AddKeybindingsFn`.
3. **`Gui.GetInitialKeybindings`** (`pkg/gui/keybindings.go`) walks every
   context (from `gui.State.Contexts.Flatten()`) and calls
   `context.GetKeybindings(opts)`, which merges all the per-controller
   functions registered on that context (`pkg/gui/context/base_context.go`,
   `GetKeybindings`). Custom-command bindings from user config are prepended
   here so they take precedence.
4. **`resetKeybindings`** registers each binding with gocui.
5. **The three surfaces read the same bindings:**
   - The options bar reads the *current context's* bindings plus globals
     (`options_map.go`), filters to `DisplayOnScreen && !IsDisabled()`, and
     renders `GetShortDescription()` alongside the label of `Keys[0]`.
   - The `?` menu reads the full set via
     `GetInitialKeybindingsWithCustomCommands` and includes any binding with a
     non-empty `GetDescription()`, grouping by view/tag
     (`options_menu_action.go:getBindings`).
   - The cheatsheet generator instantiates the app headlessly per language,
     calls `Gui.GetCheatsheetKeybindings()` (`keybindings.go:48`), and writes
     the Markdown tables from `Description`/`Alternative`/`Tooltip`/`Tag`/
     `ViewName`.

So: set the right fields on the `Binding`, and all three surfaces pick it up.
Nothing else needs wiring.

## Adding or changing a hint: the steps

### 1. Edit the controller's `GetKeybindings`

Return a `*types.Binding` (or modify an existing one) with at least `Keys`,
`Handler`, and `Description`. Add `ShortDescription` if the long description is
too verbose for the bottom bar, `Tooltip` for menu help, and
`DisplayOnScreen: true` if it should surface on the bottom bar. Use
`GetDisabledReason` if the action is conditional.

Keys come from the user config via `opts.GetKeys(opts.Config.<Category>.<Key>)`
— see *User-overridable keys* below.

### 2. Add the user-facing strings to the translation set

`Description`, `ShortDescription`, and `Tooltip` are fields on
`*i18n.TranslationSet`, accessed in controllers as `self.c.Tr.<FieldName>`.
There is exactly one file to edit for English:

- `pkg/i18n/english.go`:
  - Add a field to the `TranslationSet` struct (near the top of the file).
  - Add its value in the `EnglishTranslationSet()` literal (further down).
  - Try to keep the new field name within the existing column width of its
    alignment block (gofumpt re-indents the whole block when the widest name
    grows — see the project's `AGENTS.md` for the soft preference).

Rules that apply to every user-facing string, not just keybinding hints:

- **Use Go-template placeholders, never `fmt.Sprintf`-style `%s`/`%d`.** Fill
  them at the call site with `utils.ResolvePlaceholderString(str, map[string]string{...})`.
  Named placeholders help localizers and reorder safely across languages.
- **Do not edit the JSON files under `pkg/i18n/translations/`.** Those are
  maintained by Crowdin and synced automatically; unknown keys are ignored at
  load time, orphan keys are cleaned up by Crowdin later. Editing English in
  `english.go` is all that's needed — a new key automatically uses the English
  text for every language until Crowdin translations arrive.

### 3. (Only if the *key itself* should be user-overridable) Add a config field

If this is a new key the user should be able to rebind, add a field to the
relevant `KeybindingXxxConfig` struct in `pkg/config/user_config.go` *and* a
default value in the defaults literal at the bottom of that file. The
controller then reads it via `opts.GetKeys(opts.Config.<Category>.<Field>)`.

If the change touches `userConfig` fields, run `just generate` so
`docs-master/Config.md` and `schema-master/config.json` are regenerated, and
commit the regenerated files. Don't hand-edit those.

### 4. Regenerate the cheatsheet docs

Run `just generate` (= `go generate ./...`). This rewrites every
`docs-master/keybindings/Keybindings_<lang>.md` from the current bindings and
translation sets. Commit the regenerated files in the same commit as the
binding change — CI fails if they are stale.

### 5. Format, lint, build

Per the project's `AGENTS.md`: run `just format` (gofumpt), `just lint`
(golangci-lint), and `just build` before committing.

## Pitfalls

- **A binding with no `Description` (and no `Alternative`) is invisible to the
  menu and cheatsheet.** `getBindingSections` in `pkg/cheatsheet/generate.go`
  filters such bindings out, and `OptionsMenuAction.getBindings` only includes
  bindings with a non-empty `GetDescription()`. The binding still *works* — it
  just isn't discoverable. Set a description unless the binding is intentionally
  hidden.

- **`DescriptionFunc` is *not* used by the cheatsheet generator.** It reads the
  plain `Description` field, because the generator runs headlessly with no live
  state. When you add a dynamic description you must still provide a static
  `Description` that reads well in the cheatsheet, or the cheatsheet will show
  an empty/placeholder label.

- **Forgotten `DisplayOnScreen: true`** is the reason a key works but never
  appears on the bottom bar. The menu and cheatsheet don't need it, but the
  bar does.

- **Forgotten `just generate`** leaves the cheatsheet docs stale. CI catches
  this, but the failure is noisy; run it whenever you add, remove, rename, or
  rebind a key or change a description/tooltip.

- **Adding a binding for a brand-new view** requires a matching entry in the
  `localisedTitle` map in `pkg/cheatsheet/generate.go:100`, plus a
  `<View>Title` field in `TranslationSet` (english.go). If you forget, the
  generator `panic`s with `title not found for <view>` — the loud signal that
  the mapping is missing.

- **Bottom bar space is scarce.** The bar truncates with `…` when it overflows
  the view width, so a long `ShortDescription` (or too many `DisplayOnScreen`
  bindings in one context) pushes later hints off-screen. Prefer a compact
  `ShortDescription` and only flag the keys users actively need in that context.
  The style guide at the top of `renderContextOptionsMap` says: use the default
  options color for most bindings, and reserve a distinct `DisplayStyle` for
  keys the user is likely to want in a specific mode (e.g. cherry-picking paste
  is colored, the rest are default).

- **Disabled bindings disappear from the bar.** `IsDisabled()` bindings are
  filtered out of the options bar entirely (no strikethrough), but they *do*
  appear in the menu with a `Disabled: <reason>` tooltip prefix. If a binding
  should sometimes be visible on the bar and sometimes not, `GetDisabledReason`
  is the lever — return `nil` when enabled, a reason when not.

## Dynamic descriptions

When a binding's meaning depends on context (e.g. the `Return`/`escape` key
means "cancel", "back", "close", etc. depending on what's open), use
`DescriptionFunc` and/or `ShortDescriptionFunc`:

```go
{
    Keys:            opts.GetKeys(opts.Config.Universal.Return),
    Handler:         self.escape,
    Description:     self.c.Tr.Cancel,          // static, used by cheatsheet
    DescriptionFunc: self.escapeDescription,    // dynamic, used by menu
    DisplayOnScreen: true,
}
```

The function must be cheap (it runs on every render of the menu / bar). Keep
the static `Description` as a sensible default; the cheatsheet always uses it.

## Quick reference: which file does what

| File | Role |
|---|---|
| `pkg/gui/types/keybindings.go` | `Binding` struct and resolution helpers |
| `pkg/gui/types/context.go` | `KeybindingsOpts`, `HasKeybindings` interface |
| `pkg/gui/types/common.go` | `DisabledReason` struct |
| `pkg/gui/keybindings.go` | Top-level assembly: `GetInitialKeybindings`, `GetCheatsheetKeybindings`, `resetKeybindings` |
| `pkg/gui/controllers/*.go` | Each controller's `GetKeybindings(opts) []*Binding` — where most bindings are written |
| `pkg/gui/controllers/attach.go` | Registers each controller's `GetKeybindings` onto its context |
| `pkg/gui/context/base_context.go` | Merges all per-controller binding funcs on a context |
| `pkg/gui/controllers/options_menu_action.go` | Builds the `?` keybindings menu |
| `pkg/gui/controllers/menu_controller.go` | Menu controller; writes selected item tooltip to the `Tooltip` view |
| `pkg/gui/context/menu_context.go` | Menu view model; binding precedence; `@`-prefix key filtering |
| `pkg/gui/controllers/helpers/confirmation_helper.go` | `TooltipForMenuItem`; menu/tooltip layout |
| `pkg/gui/options_map.go` | Bottom options-bar renderer |
| `pkg/gui/layout.go` | Triggers the options-bar render each layout pass |
| `pkg/gui/views.go` | View registry (`Options`, `Tooltip`, `Menu`, …) |
| `pkg/config/keynames.go` | `LabelForKey` / `KeyFromLabel` / `GetValidatedKeyBindingKeys` — key string ↔ `gocui.Key` |
| `pkg/config/user_config.go` | `KeybindingConfig` and per-category structs — user-overridable key strings |
| `pkg/i18n/english.go` | `TranslationSet` and `EnglishTranslationSet()`; the only English strings file to edit |
| `pkg/i18n/i18n.go` | Translation loading; `GetTranslationSets` (used by the generator) |
| `pkg/cheatsheet/generate.go` | Markdown cheatsheet generator; `localisedTitle` map; section/column formatting |
| `pkg/cheatsheet/generator.go` | `//go:build ignore` entry point for `go generate` |
| `justfile` | `generate` recipe runs `go generate ./...` |

## TL;DR

To add a keybinding hint:

1. Set `Description` (and optionally `ShortDescription`, `Tooltip`,
   `DisplayOnScreen: true`, `Tag`, `Alternative`, `GetDisabledReason`,
   `DisplayStyle`) on a `*types.Binding` returned from your controller's
   `GetKeybindings`.
2. Add any new user-facing strings to `TranslationSet` in
   `pkg/i18n/english.go` (Go-template placeholders, not `%s`). Don't touch the
   other translation files.
3. If the *key* should be user-overridable, add it to `pkg/config/user_config.go`
   (struct field + default). Run `just generate` if you touched `userConfig`.
4. Run `just generate` to refresh the cheatsheet docs, then `just format`,
   `just lint`, `just build`.