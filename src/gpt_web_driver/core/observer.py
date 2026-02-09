from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from ..nodriver_dom import dom_get_outer_html, html_to_text, wait_for_selector


def _attrs_list_to_dict(attrs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    it = iter(attrs)
    for k in it:
        try:
            v = next(it)
        except StopIteration:
            break
        out[str(k)] = str(v)
    return out


async def _dom_get_document(page: Any, uc: Any) -> Any:
    # Prefer shallow document since we only need root nodeId.
    try:
        return await page.send(uc.cdp.dom.get_document(1, True))
    except TypeError:
        return await page.send(uc.cdp.dom.get_document(-1, True))


async def _dom_query_selector_all(page: Any, uc: Any, root_node_id: Any, selector: str) -> list[Any]:
    try:
        res = await page.send(uc.cdp.dom.query_selector_all(root_node_id, selector))
    except TypeError:
        res = await page.send(uc.cdp.dom.query_selector_all(node_id=root_node_id, selector=selector))
    # nodriver returns a list of NodeId-like values.
    return list(res or [])


async def _dom_get_attributes(page: Any, uc: Any, node_id: Any) -> dict[str, str]:
    attrs_list = await page.send(uc.cdp.dom.get_attributes(node_id))
    return _attrs_list_to_dict(list(attrs_list or []))


async def _dom_query_selector(page: Any, uc: Any, root_node_id: Any, selector: str) -> Any:
    try:
        return await page.send(uc.cdp.dom.query_selector(root_node_id, selector))
    except TypeError:
        return await page.send(uc.cdp.dom.query_selector(node_id=root_node_id, selector=selector))


@dataclass(frozen=True)
class ChatMessage:
    role: str
    message_id: str
    text: str


async def extract_chat_messages(
    page: Any,
    *,
    message_selector: str = "[data-message-author-role]",
    content_selector: str = ".whitespace-pre-wrap, .markdown",
    timeout_s: float = 20.0,
    uc_module: Optional[Any] = None,
) -> list[ChatMessage]:
    """
    Extract chat messages using CDP DOM reads only (no JS evaluation).
    """
    if float(timeout_s) > 0:
        await wait_for_selector(page, message_selector, timeout_s=float(timeout_s))

    uc = uc_module
    if uc is None:
        import nodriver as uc  # type: ignore[assignment]

    doc = await _dom_get_document(page, uc)
    root_id = getattr(doc, "node_id", None)
    if root_id is None:
        root = getattr(doc, "root", None)
        root_id = getattr(root, "node_id", None) if root is not None else None
    if root_id is None:
        # Extremely defensive; in practice nodriver returns a document/root node with node_id.
        raise RuntimeError("DOM.getDocument returned no root node_id")

    node_ids = await _dom_query_selector_all(page, uc, root_id, str(message_selector))
    messages: list[ChatMessage] = []
    for node_id in node_ids:
        attrs = await _dom_get_attributes(page, uc, node_id)
        role = attrs.get("data-message-author-role", "unknown")
        message_id = attrs.get("data-message-id", "")

        # Prefer an inner content node for text extraction.
        target_node_id = node_id
        try:
            inner = await _dom_query_selector(page, uc, node_id, str(content_selector))
            if inner:
                target_node_id = inner
        except Exception:
            pass

        outer_html = await dom_get_outer_html(page, int(target_node_id))
        text = html_to_text(outer_html)
        if text:
            messages.append(ChatMessage(role=str(role), message_id=str(message_id), text=str(text)))
    return messages


async def last_assistant_message_text(
    page: Any,
    *,
    message_selector: str = "[data-message-author-role]",
    content_selector: str = ".whitespace-pre-wrap, .markdown",
    timeout_s: float = 20.0,
    uc_module: Optional[Any] = None,
) -> Optional[str]:
    """
    Returns the last assistant message text if present, else None.
    """
    msgs = await extract_chat_messages(
        page,
        message_selector=message_selector,
        content_selector=content_selector,
        timeout_s=timeout_s,
        uc_module=uc_module,
    )
    for m in reversed(msgs):
        if m.role == "assistant":
            return m.text
    return None


async def wait_for_assistant_reply(
    page: Any,
    *,
    message_selector: str = "[data-message-author-role]",
    content_selector: str = ".whitespace-pre-wrap, .markdown",
    baseline_text: str | None = None,
    timeout_s: float = 60.0,
    stable_s: float = 1.2,
    poll_s: float = 0.25,
    uc_module: Optional[Any] = None,
    on_poll: Callable[[], None] | None = None,
    interruption_keywords: Iterable[str] = ("challenge", "verify", "captcha"),
) -> str:
    """
    Wait for an assistant reply to appear and stop changing for `stable_s`.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + float(timeout_s)
    stable_deadline: float | None = None

    last: str | None = None
    while True:
        if loop.time() >= deadline:
            raise TimeoutError("Timed out waiting for assistant reply.")

        txt = await last_assistant_message_text(
            page,
            message_selector=message_selector,
            content_selector=content_selector,
            timeout_s=0.0,
            uc_module=uc_module,
        )

        if baseline_text is not None and txt == baseline_text:
            txt = None

        # Dead man's switch: detect interruption keywords anywhere in the assistant output.
        blob = (txt or "").lower()
        if any(str(k).lower() in blob for k in interruption_keywords):
            raise RuntimeError("Automation interrupted: potential verification/challenge detected.")

        if txt and txt != last:
            last = txt
            stable_deadline = loop.time() + float(stable_s)

        if txt and stable_deadline is not None and loop.time() >= stable_deadline:
            return str(txt)

        if on_poll is not None:
            try:
                on_poll()
            except Exception:
                pass

        await asyncio.sleep(float(poll_s))
