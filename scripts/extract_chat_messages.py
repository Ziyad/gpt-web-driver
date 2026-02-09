from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Optional

import nodriver as uc

from gpt_web_driver.nodriver_dom import wait_for_selector
from gpt_web_driver.stealth import stealth_init


class _HTMLToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in {"p", "div", "li", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self._chunks.append(data)

    def text(self) -> str:
        s = "".join(self._chunks)
        # Normalize whitespace without destroying intentional newlines.
        s = re.sub(r"[ \t]+\n", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()


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


async def _dom_get_document(page: Any, *, depth: int = 1, pierce: bool = True) -> Any:
    # nodriver CDP API can differ across versions; be defensive about call signatures.
    try:
        return await page.send(uc.cdp.dom.get_document(int(depth), bool(pierce)))
    except TypeError:
        try:
            return await page.send(uc.cdp.dom.get_document(depth=int(depth), pierce=bool(pierce)))
        except TypeError:
            return await page.send(uc.cdp.dom.get_document())


async def _dom_query_selector_all(page: Any, root_node_id: Any, selector: str) -> list[Any]:
    try:
        res = await page.send(uc.cdp.dom.query_selector_all(root_node_id, str(selector)))
    except TypeError:
        res = await page.send(uc.cdp.dom.query_selector_all(node_id=root_node_id, selector=str(selector)))
    return list(res or [])


async def _dom_query_selector(page: Any, root_node_id: Any, selector: str) -> Any:
    try:
        return await page.send(uc.cdp.dom.query_selector(root_node_id, str(selector)))
    except TypeError:
        return await page.send(uc.cdp.dom.query_selector(node_id=root_node_id, selector=str(selector)))


async def _dom_get_attributes(page: Any, node_id: Any) -> dict[str, str]:
    try:
        attrs_list = await page.send(uc.cdp.dom.get_attributes(node_id))
    except TypeError:
        attrs_list = await page.send(uc.cdp.dom.get_attributes(node_id=node_id))
    return _attrs_list_to_dict(list(attrs_list or []))


async def _dom_get_outer_html(page: Any, node_id: Any) -> str:
    try:
        res = await page.send(uc.cdp.dom.get_outer_html(node_id))
    except TypeError:
        res = await page.send(uc.cdp.dom.get_outer_html(node_id=node_id))
    return str(res or "")


@dataclass(frozen=True)
class ChatMessage:
    role: str
    message_id: str
    text: str


async def extract_messages(
    page: Any,
    *,
    message_selector: str,
    content_selector: str,
    timeout_s: float,
) -> list[ChatMessage]:
    await wait_for_selector(page, message_selector, timeout_s=timeout_s)

    # Get the document root nodeId, then select message nodes. We only need the root nodeId for
    # DOM.querySelectorAll; avoid fetching the full tree.
    doc = await _dom_get_document(page, depth=1, pierce=True)
    root_id = getattr(doc, "node_id", None)
    if root_id is None:
        root = getattr(doc, "root", None)
        root_id = getattr(root, "node_id", None) if root is not None else None
    if root_id is None:
        # Extremely defensive; in practice nodriver returns a document/root node with node_id.
        raise RuntimeError("DOM.getDocument returned no root node_id")

    node_ids = await _dom_query_selector_all(page, root_id, message_selector)

    messages: list[ChatMessage] = []
    for node_id in node_ids:
        attrs = await _dom_get_attributes(page, node_id)
        role = attrs.get("data-message-author-role", "unknown")
        message_id = attrs.get("data-message-id", "")

        # Prefer the "inner" content area for text extraction.
        try:
            content_node_id = await _dom_query_selector(page, node_id, content_selector)
        except Exception:
            content_node_id = None

        target_node_id = content_node_id or node_id
        outer_html = await _dom_get_outer_html(page, target_node_id)

        parser = _HTMLToText()
        parser.feed(outer_html)
        text = parser.text()
        if text:
            messages.append(ChatMessage(role=role, message_id=message_id, text=text))
    return messages


async def _run(url: str, *, timeout_s: float) -> int:
    # Headed execution only: this script is intended to mirror the main project's
    # "no headless" doctrine.
    browser = await uc.start(headless=False)
    try:
        page = await browser.get(url)
        await stealth_init(page, uc_module=uc)

        # Matches sample-body.html (ChatGPT-like) and any similar pages that tag messages.
        message_selector = "[data-message-author-role]"
        # Try common containers within a message node first.
        content_selector = ".whitespace-pre-wrap, .markdown"

        msgs = await extract_messages(
            page,
            message_selector=message_selector,
            content_selector=content_selector,
            timeout_s=timeout_s,
        )

        print(json.dumps([m.__dict__ for m in msgs], indent=2))
        return 0
    finally:
        # nodriver's Browser.stop() is synchronous.
        try:
            browser.stop()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract chat messages from a page like sample-body.html.")
    ap.add_argument("--url", required=True)
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    return asyncio.run(_run(str(args.url), timeout_s=float(args.timeout)))


if __name__ == "__main__":
    raise SystemExit(main())
