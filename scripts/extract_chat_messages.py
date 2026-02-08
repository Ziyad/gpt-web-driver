from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Optional

import nodriver as uc

from spec2_hybrid.nodriver_dom import wait_for_selector
from spec2_hybrid.stealth import stealth_init


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

    # Query the full DOM tree, then select message nodes.
    doc = await page.send(uc.cdp.dom.get_document(-1, True))
    node_ids = await page.send(uc.cdp.dom.query_selector_all(doc.node_id, message_selector))

    messages: list[ChatMessage] = []
    for node_id in node_ids:
        attrs_list = await page.send(uc.cdp.dom.get_attributes(node_id))
        attrs = _attrs_list_to_dict(attrs_list)
        role = attrs.get("data-message-author-role", "unknown")
        message_id = attrs.get("data-message-id", "")

        # Prefer the "inner" content area for text extraction.
        try:
            content_node_id = await page.send(uc.cdp.dom.query_selector(node_id, content_selector))
        except Exception:
            content_node_id = None

        target_node_id = content_node_id or node_id
        outer_html = await page.send(uc.cdp.dom.get_outer_html(target_node_id))

        parser = _HTMLToText()
        parser.feed(outer_html)
        text = parser.text()
        if text:
            messages.append(ChatMessage(role=role, message_id=message_id, text=text))
    return messages


async def _run(url: str, *, headless: bool, timeout_s: float) -> int:
    browser = await uc.start(headless=headless)
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
    ap.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    args = ap.parse_args()

    return asyncio.run(_run(str(args.url), headless=bool(args.headless), timeout_s=float(args.timeout)))


if __name__ == "__main__":
    raise SystemExit(main())
