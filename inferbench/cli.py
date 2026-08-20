from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="InferBench Local benchmark console")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="bind port (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="enable development reload")
    parser.add_argument("--data-dir", help="directory for local SQLite data")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["INFERBENCH_DATA_DIR"] = args.data_dir
    uvicorn.run("inferbench.main:app", host=args.host, port=args.port, reload=args.reload)
