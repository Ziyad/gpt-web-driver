from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .runner import FlowRunner, RunConfig


class FlowSpecError(ValueError):
    pass


_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_template(s: str, vars: dict[str, Any]) -> str:
    """
    Minimal `{{var}}` templating.
    """

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in vars:
            raise FlowSpecError(f"unknown variable in template: {name!r}")
        v = vars[name]
        return "" if v is None else str(v)

    return _TEMPLATE_RE.sub(_sub, str(s))


def render_obj(obj: Any, vars: dict[str, Any]) -> Any:
    """
    Recursively render templates in strings inside JSON-ish objects.
    """
    if isinstance(obj, str):
        return render_template(obj, vars)
    if isinstance(obj, list):
        return [render_obj(v, vars) for v in obj]
    if isinstance(obj, dict):
        return {str(k): render_obj(v, vars) for k, v in obj.items()}
    return obj


def load_flow(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise FlowSpecError(f"flow file not found: {path}") from e

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FlowSpecError(f"invalid JSON in flow file: {path}: {e}") from e

    if not isinstance(obj, dict):
        raise FlowSpecError("flow spec must be a JSON object")
    return obj


@dataclass(frozen=True)
class FlowResult:
    value: Optional[str]
    vars: dict[str, Any]


async def run_flow(
    config: RunConfig,
    flow_spec: dict[str, Any],
    *,
    vars: dict[str, Any] | None = None,
    emit: Callable[[dict[str, Any]], None] | None = None,
    include_text_in_events: bool = False,
) -> FlowResult:
    if not isinstance(flow_spec, dict):
        raise FlowSpecError("flow spec must be a JSON object")

    base_vars = flow_spec.get("vars") or {}
    if not isinstance(base_vars, dict):
        raise FlowSpecError("'vars' must be an object if provided")

    ctx: dict[str, Any] = dict(base_vars)
    if vars:
        ctx.update(vars)

    steps = flow_spec.get("steps")
    if not isinstance(steps, list):
        raise FlowSpecError("'steps' must be a list")

    async with FlowRunner(config, emit=emit, include_text_in_events=include_text_in_events) as runner:
        for idx, raw_step in enumerate(steps):
            if not isinstance(raw_step, dict):
                raise FlowSpecError(f"step {idx} must be an object")

            step = render_obj(raw_step, ctx)
            action = step.get("action")
            if not isinstance(action, str) or not action.strip():
                raise FlowSpecError(f"step {idx} missing 'action'")
            action = action.strip()

            if emit is not None:
                emit({"event": "flow.step.start", "i": int(idx), "action": str(action)})

            if action == "navigate":
                url = step.get("url")
                if not isinstance(url, str) or not url:
                    raise FlowSpecError(f"step {idx} navigate requires 'url'")
                await runner.navigate(url)

            elif action == "click":
                selector = step.get("selector")
                if not isinstance(selector, str) or not selector:
                    raise FlowSpecError(f"step {idx} click requires 'selector'")
                within = step.get("within")
                if within is not None and (not isinstance(within, str) or not within):
                    raise FlowSpecError(f"step {idx} click 'within' must be a non-empty string")
                await runner.click(selector, within_selector=within)

            elif action == "type":
                selector = step.get("selector")
                text = step.get("text")
                if not isinstance(selector, str) or not selector:
                    raise FlowSpecError(f"step {idx} type requires 'selector'")
                if text is not None and not isinstance(text, str):
                    raise FlowSpecError(f"step {idx} type 'text' must be a string or null")

                within = step.get("within")
                if within is not None and (not isinstance(within, str) or not within):
                    raise FlowSpecError(f"step {idx} type 'within' must be a non-empty string")

                click_first = step.get("click_first", True)
                press_enter = step.get("press_enter", False)
                post_click_delay_s = step.get("post_click_delay_s", None)
                if not isinstance(click_first, bool):
                    raise FlowSpecError(f"step {idx} type 'click_first' must be a boolean")
                if not isinstance(press_enter, bool):
                    raise FlowSpecError(f"step {idx} type 'press_enter' must be a boolean")
                if post_click_delay_s is not None and not isinstance(post_click_delay_s, (int, float)):
                    raise FlowSpecError(f"step {idx} type 'post_click_delay_s' must be a number")

                await runner.type(
                    selector,
                    (text or ""),
                    within_selector=within,
                    click_first=bool(click_first),
                    press_enter=bool(press_enter),
                    post_click_delay_s=(float(post_click_delay_s) if post_click_delay_s is not None else None),
                )

            elif action == "press":
                key = step.get("key")
                if not isinstance(key, str) or not key:
                    raise FlowSpecError(f"step {idx} press requires 'key'")
                await runner.press(key)

            elif action == "sleep":
                seconds = step.get("seconds")
                if not isinstance(seconds, (int, float)):
                    raise FlowSpecError(f"step {idx} sleep requires 'seconds' (number)")
                await asyncio.sleep(float(seconds))

            elif action == "wait_for_selector":
                selector = step.get("selector")
                if not isinstance(selector, str) or not selector:
                    raise FlowSpecError(f"step {idx} wait_for_selector requires 'selector'")
                within = step.get("within")
                if within is not None and (not isinstance(within, str) or not within):
                    raise FlowSpecError(f"step {idx} wait_for_selector 'within' must be a non-empty string")
                timeout_s = step.get("timeout_s")
                if timeout_s is not None and not isinstance(timeout_s, (int, float)):
                    raise FlowSpecError(f"step {idx} wait_for_selector 'timeout_s' must be a number")
                await runner.wait_for_selector(
                    selector,
                    within_selector=within,
                    timeout_s=(float(timeout_s) if timeout_s is not None else None),
                )

            elif action == "wait_for_text":
                selector = step.get("selector")
                contains = step.get("contains")
                if not isinstance(selector, str) or not selector:
                    raise FlowSpecError(f"step {idx} wait_for_text requires 'selector'")
                if not isinstance(contains, str) or not contains:
                    raise FlowSpecError(f"step {idx} wait_for_text requires 'contains'")
                within = step.get("within")
                if within is not None and (not isinstance(within, str) or not within):
                    raise FlowSpecError(f"step {idx} wait_for_text 'within' must be a non-empty string")
                timeout_s = step.get("timeout_s")
                poll_s = step.get("poll_s", None)
                if timeout_s is not None and not isinstance(timeout_s, (int, float)):
                    raise FlowSpecError(f"step {idx} wait_for_text 'timeout_s' must be a number")
                if poll_s is not None and not isinstance(poll_s, (int, float)):
                    raise FlowSpecError(f"step {idx} wait_for_text 'poll_s' must be a number")

                text = await runner.wait_for_text(
                    selector,
                    contains=str(contains),
                    within_selector=within,
                    timeout_s=(float(timeout_s) if timeout_s is not None else None),
                    poll_s=(float(poll_s) if poll_s is not None else None),
                )
                into = step.get("into")
                if into is not None:
                    if not isinstance(into, str) or not into:
                        raise FlowSpecError(f"step {idx} wait_for_text 'into' must be a non-empty string")
                    ctx[str(into)] = text

            elif action == "extract_text":
                selector = step.get("selector")
                if not isinstance(selector, str) or not selector:
                    raise FlowSpecError(f"step {idx} extract_text requires 'selector'")
                within = step.get("within")
                if within is not None and (not isinstance(within, str) or not within):
                    raise FlowSpecError(f"step {idx} extract_text 'within' must be a non-empty string")
                timeout_s = step.get("timeout_s")
                if timeout_s is not None and not isinstance(timeout_s, (int, float)):
                    raise FlowSpecError(f"step {idx} extract_text 'timeout_s' must be a number")

                into = step.get("into", "result")
                if not isinstance(into, str) or not into:
                    raise FlowSpecError(f"step {idx} extract_text 'into' must be a non-empty string")

                text = await runner.extract_text(
                    selector,
                    within_selector=within,
                    timeout_s=(float(timeout_s) if timeout_s is not None else None),
                )
                ctx[str(into)] = text

            elif action == "set":
                name = step.get("name")
                if not isinstance(name, str) or not name:
                    raise FlowSpecError(f"step {idx} set requires 'name'")
                ctx[str(name)] = step.get("value")

            else:
                raise FlowSpecError(f"step {idx} has unknown action: {action!r}")

            if emit is not None:
                emit({"event": "flow.step.end", "i": int(idx), "action": str(action)})

    result_tmpl = flow_spec.get("result")
    if result_tmpl is None:
        value = ctx.get("result")
        return FlowResult(value=("" if value is None else str(value)), vars=ctx)

    if not isinstance(result_tmpl, str):
        raise FlowSpecError("'result' must be a string if provided")

    return FlowResult(value=render_template(result_tmpl, ctx), vars=ctx)

