"""Named, bounded owner-process fixture for real orphan-liveness checks."""
from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=('exit', 'hold'))
    args = parser.parse_args()
    print(json.dumps({'pid': os.getpid(), 'mode': args.mode}), flush=True)
    if args.mode == 'hold':
        # The parent closes this owner cleanly after probing its live PID.
        sys.stdin.readline()


if __name__ == '__main__':
    main()
