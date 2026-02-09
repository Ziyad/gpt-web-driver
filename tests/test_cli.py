from __future__ import annotations


def test_serve_has_longer_default_timeout_than_run():
    from gpt_web_driver.cli import build_parser

    p = build_parser()

    ns_run = p.parse_args(["run", "--url", "https://example.com/"])
    assert ns_run.timeout == 20.0

    ns_serve = p.parse_args(["serve", "--url", "https://example.com/"])
    assert ns_serve.timeout == 90.0

