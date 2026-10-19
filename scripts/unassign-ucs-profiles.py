#!/usr/bin/env python3
# Copyright (c) 2026 Cisco and/or its affiliates.
# Licensed under the Cisco Sample Code License, Version 1.1. See LICENSE.
"""Bounded server unassignment; unknown observation prevents downstream deletion."""
import json
import re
import subprocess
import sys
import time


def observe(name):
    result = subprocess.run(['isctl', 'get', 'server', 'profile', '--filter',
                             f"Name eq '{name}'", '-o', 'json'],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('server profile observation failed')
    try:
        rows = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError('invalid server profile observation') from error
    if not isinstance(rows, list) or len(rows) > 1:
        raise RuntimeError('ambiguous server profile observation')
    if not rows:
        return None
    row = rows[0]
    if not isinstance(row, dict) or row.get('Name') != name or not row.get('Moid'):
        raise RuntimeError('server profile identity mismatch')
    state = (row.get('ConfigContext') or {}).get('ConfigState')
    if not isinstance(state, str) or not state:
        raise RuntimeError('server profile state unavailable')
    return row['Moid'], state


def unassign(names, wait=600, interval=30):
    if not names or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', n) for n in names):
        raise ValueError('explicit server profile names required')
    for name in names:
        initial = observe(name)
        if initial is None:
            print(f'{name}: absent in successful observation')
            continue
        moid, state = initial
        if state == 'Not-assigned':
            continue
        if state not in {'Associated', 'Assigned'}:
            raise RuntimeError(f'{name}: cannot unassign from observed state {state}')
        result = subprocess.run(['isctl', 'update', 'server', 'profile', 'moid', moid,
                                 '--Action', 'Unassign'], capture_output=True, text=True,
                                timeout=60)
        if result.returncode:
            raise RuntimeError('server profile unassignment failed')
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            current = observe(name)
            if current is None or current[0] != moid:
                raise RuntimeError('server profile disappeared or changed during unassignment')
            if current[1] == 'Not-assigned':
                break
            if current[1] in {'Failed', 'ConfigureFailed'}:
                raise RuntimeError('server profile unassignment entered failed state')
            time.sleep(interval)
        else:
            raise RuntimeError('timeout waiting for server profile unassignment')
        print(f'{name}: confirmed unassigned')


if __name__ == '__main__':
    try:
        unassign(sys.argv[1:])
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
