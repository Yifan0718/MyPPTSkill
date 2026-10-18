#!/usr/bin/env python3
"""Guarded updater. Default: stage only; no local rule is overwritten."""
from local_update_guard import main
if __name__ == '__main__':
    raise SystemExit(main())
