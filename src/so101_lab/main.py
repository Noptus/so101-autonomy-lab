import argparse
import os
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="SO-101 Autonomy Lab (starts in simulation)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default=os.getenv("SO101_DATA_DIR", ".so101-lab"))
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1") and len(os.getenv("SO101_REMOTE_TOKEN", "")) < 32:
        parser.error("Remote binding requires SO101_REMOTE_TOKEN of at least 32 characters; use a TLS proxy")
    from so101_lab.server.api import create_app

    uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port, workers=1, access_log=False)
