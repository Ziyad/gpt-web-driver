# Interface

## CLI Output (`--output jsonl`)

When `--output jsonl` is set, `gpt-web-driver` writes a stream of JSON objects to stdout (one per line).

Conventions:
- every event has an `event` string
- the CLI adds a `ts` field (Unix epoch seconds) if not present
- logs go to stderr

### Events

`navigate`
- `url`: string

`interact.point`
- `selector`: string
- `action`: string (e.g. `interact`, `click`)
- `within`: string (optional; root selector used to scope the query)
- `viewport_x`, `viewport_y`: number (CSS pixels, viewport-relative)
- `scale_x`, `scale_y`: number (viewport->screen scale)
- `screen_x`, `screen_y`: number (viewport coords * scale + offsets)
- `final_x`, `final_y`: number (after jitter/noise)

`os.move_to`
- `x`, `y`: number (screen pixels)
- `duration_s`: number
- `dry_run`: boolean

`os.click`
- `dry_run`: boolean

`os.human_type`
- `chars`: number
- `min_delay_s`, `max_delay_s`: number
- `dry_run`: boolean
- `text`: string (only if `--include-text-in-output`)

`os.write_char` (optional)
- `dry_run`: boolean
- `char`: string (only if `--include-text-in-output`)

`os.press`
- `key`: string
- `dry_run`: boolean

`os.key_down`
- `key`: string
- `dry_run`: boolean

`os.key_up`
- `key`: string
- `dry_run`: boolean

`os.hotkey`
- `keys`: string[]
- `dry_run`: boolean

`os.scroll`
- `clicks`: number
- `dry_run`: boolean

`flow.step.start`
- `i`: number (0-based step index)
- `action`: string

`flow.step.end`
- `i`: number (0-based step index)
- `action`: string

`wait_for_text.ok`
- `selector`: string
- `within`: string (optional)
- `contains`: string
- `chars`: number

`result`
- `value`: string | null

`doctor`
- `python`: string
- `platform`: string
- `machine`: string
- `is_wsl`: boolean
- `display.DISPLAY`: string | null
- `display.WAYLAND_DISPLAY`: string | null
- `effective_dry_run`: boolean
- `default_download_browser`: boolean
- `default_browser_channel`: string
- `default_browser_sandbox`: boolean
- `browser_cache_dir`: string
- `browser_resolved`: string | null
- `browser_error`: string | null
- `cdp`: object | null

`error`
- `error_type`: string
- `error`: string

`calibrate.start`
- `url`: string

`calibrate.point`
- `point`: string (`A` or `B`)
- `viewport_x`, `viewport_y`: number
- `screen_x`, `screen_y`: number

`calibrate.result`
- `scale_x`, `scale_y`: number
- `offset_x`, `offset_y`: number

`calibrate.write`
- `path`: string
