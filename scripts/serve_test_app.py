from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    # Allow running from a repo checkout without requiring an editable install.
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if src_root.exists():
        sys.path.insert(0, str(src_root))

    from gpt_web_driver.demo_server import serve_directory

    ap = argparse.ArgumentParser(description="Serve the local gpt-web-driver test webapp.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0, help="0 chooses an ephemeral port")
    args = ap.parse_args()

    web_root = repo_root / "webapp"
    if not web_root.exists():
        raise SystemExit(f"web root does not exist: {web_root}")

    srv = serve_directory(web_root, host=args.host, port=args.port)
    url = f"{srv.base_url}/index.html"
    print(url, flush=True)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
