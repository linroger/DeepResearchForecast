#!/usr/bin/env python3
"""Run one sealed world generation; no social-platform dependency is imported."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulation-dir', required=True, type=Path)
    parser.add_argument('--lock-fd', type=int)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--launch-id')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services.world_simulation.service import run_child
    try:
        return run_child(args.simulation_dir, expected_manifest_sha256=args.manifest_sha256,
                         launch_id=args.launch_id, launch_lock_fd=args.lock_fd)
    finally:
        if args.lock_fd is not None:
            os.close(args.lock_fd)


if __name__ == '__main__':
    raise SystemExit(main())
