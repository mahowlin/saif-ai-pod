#!/usr/bin/env python3
# Copyright (c) 2026 Cisco and/or its affiliates.
# Licensed under the Cisco Sample Code License, Version 1.1. See LICENSE.
"""Select existing target-owned UCS profile files for the reusable workflow."""
import json
import os
from pathlib import Path
import re

import yaml


def select(root, target, operation, domain):
    if operation not in {'Plan', 'Stage', 'Activate', 'Deactivate', 'Delete'}:
        raise ValueError('unknown UCS operation')
    allowed = {'Unchanged'}
    if operation in {'Stage', 'Activate'}:
        allowed.add('Deployed')
    if operation in {'Deactivate', 'Delete'}:
        allowed.add('Unassigned')
    if domain not in allowed:
        raise ValueError('domain state is incompatible with selected UCS operation')
    profiles = {}
    files = {}
    for state in ('active', 'inactive'):
        for path in sorted((root / state).glob('*.ezi.yaml')):
            document = yaml.safe_load(path.read_text())
            for organization in (document or {}).values():
                for profile in (organization.get('profiles') or {}).get('server', []):
                    name = profile.get('name', '')
                    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in profiles:
                        raise ValueError('invalid or duplicate UCS server profile name')
                    if path.name in files and files[path.name] != name:
                        raise ValueError('profile file contains multiple servers; cannot move independently')
                    profiles[name] = path.name
                    files[path.name] = name
    names = sorted(profiles) if target == 'ALL' else [target]
    if not names or any(name not in profiles for name in names):
        raise ValueError('server target is absent from declared active/inactive profile inventory')
    return names, {name: profiles[name] for name in names}


def domain_profile(root):
    names = []
    for path in root.glob('*.ezi.yaml'):
        for organization in (yaml.safe_load(path.read_text()) or {}).values():
            names.extend(profile.get('name', '') for profile in (organization.get('profiles') or {}).get('domain', []))
    if len(names) != 1 or not re.fullmatch(r'[A-Za-z0-9_.-]+', names[0]):
        raise ValueError('domain operation requires one unambiguous declared domain profile')
    return names[0]


if __name__ == '__main__':
    names, files = select(Path('ucs/defaults/profiles'), os.environ['SERVER_TARGET'],
                          os.environ['OPERATION'], os.environ['DOMAIN_STATE'])
    domain = domain_profile(Path('ucs/defaults/profiles')) if os.environ['DOMAIN_STATE'] != 'Unchanged' else ''
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('domain=' + domain + '\n')
        output.write('list=' + ' '.join(names) + '\n')
        output.write('profiles=' + json.dumps(names, separators=(',', ':')) + '\n')
        output.write('profile_list=' + ' '.join(names) + '\n')
        output.write('files=' + json.dumps(files, separators=(',', ':')) + '\n')
