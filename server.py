#!/usr/bin/env python3
"""
Modular Flow Engine HTTP Service

Starts the FastAPI server for the flow engine API.

Usage:
    python server.py                    # Start on default port 9847
    python server.py --port 8080        # Start on custom port
    FLOW_ENGINE_WORKERS=4 python server.py  # Custom worker count
"""

import argparse
import os
import sys
from pathlib import Path

# Ensure package is importable
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(
        description="Modular Flow Engine HTTP Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9847,
        help="Port to listen on (default: 9847)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of job queue workers (default: 2, env: FLOW_ENGINE_WORKERS)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    # Set workers via environment if provided
    if args.workers:
        os.environ["FLOW_ENGINE_WORKERS"] = str(args.workers)

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Run: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    print(f"Starting Modular Flow Engine on http://{args.host}:{args.port}")
    print(f"API docs: http://{args.host}:{args.port}/docs")
    print(f"Workers: {os.environ.get('FLOW_ENGINE_WORKERS', '2')}")
    print()

    uvicorn.run(
        "server.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
