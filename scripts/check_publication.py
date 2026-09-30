#!/usr/bin/env python3
"""Offline publication regression checks; not a complete security audit.

Requires PyYAML. Checks git-visible files, including untracked additions.
Never prints matched secret values.
"""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
errors = []


def require(condition, message):
    if not condition:
        errors.append(message)


class UniqueKeysLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently discarding settings."""


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeysLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def main():
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).decode().split("\0")
    secret_patterns = [
        r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}",
        r"GOCSPX-[A-Za-z0-9_-]{16,}",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"\bEAA[A-Za-z0-9]{80,}\b",
    ]
    for name in sorted(set(filter(None, paths))):
        p = ROOT / name
        if not p.is_file():
            continue
        require(not (p.name.startswith('.env') and p.name != '.env.example'),
                f"Local environment file included: {name}")
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        for pattern in secret_patterns:
            require(not re.search(pattern, text), f"Possible embedded secret: {name}")
        if p.suffix == '.py':
            ast.parse(text, filename=name)
        if p.suffix == '.json':
            json.loads(text)
        if p.suffix in {'.yaml', '.yml', '.conf'} and 'nginx' not in name:
            yaml.load(text, Loader=UniqueKeysLoader)
        if name.startswith(('apps/', 'frontend/', 'scripts/testing/', 'scripts/testdata')):
            if '/locales/' not in name:
                # Catch both literal characters and JSON/Python unicode escapes.
                require(not re.search(r'[\u00e4\u00f6\u00c4\u00d6]|\\u00(?:e4|f6|c4|d6)', text),
                        f"Review Finnish text outside localization: {name}")

    compose_text = (ROOT / 'docker-compose.dev.yaml').read_text()
    compose = yaml.load(compose_text, Loader=UniqueKeysLoader)
    services = compose['services']
    example = dict(re.findall(r'^([A-Z_][A-Z_0-9]*)=(.*)$',
                              (ROOT / '.env.example').read_text(), re.M))
    referenced = set(re.findall(r'\$\{([A-Z_][A-Z_0-9]*)', compose_text))
    require(not referenced - example.keys(),
            f"Compose variables missing from .env.example: {sorted(referenced - example.keys())}")
    required = set(re.findall(r'\$\{([A-Z_][A-Z_0-9]*):\?', compose_text))
    for name in required:
        require(example.get(name) == '', f"Required credential must be empty in example: {name}")
    for name, svc in services.items():
        for port in svc.get('ports', []):
            require(str(port).startswith('127.0.0.1:'), f"Non-local published port: {name}")
        for dep in svc.get('depends_on', []):
            require(dep in services, f"Unknown dependency for {name}: {dep}")
        environment = svc.get('environment', {})
        if isinstance(environment, list):
            environment = dict(item.split('=', 1) for item in environment)
        for key, value in environment.items():
            if re.search(r'PASSWORD|SECRET|API_KEY|ENCRYPTION_KEY|TOKEN$', key):
                require(str(value).startswith('${'), f"Literal credential in Compose: {name}/{key}")
        build = svc.get('build')
        if build:
            context = ROOT / (build if isinstance(build, str) else build['context'])
            dockerfile = context / (build.get('dockerfile', 'Dockerfile') if isinstance(build, dict) else 'Dockerfile')
            require(dockerfile.is_file(), f"Missing Dockerfile: {name}")
            require((context / '.dockerignore').is_file(), f"Unprotected Docker context: {name}")
        for volume in svc.get('volumes', []):
            source = volume.split(':', 1)[0]
            if source.startswith('./'):
                require((ROOT / source).exists(), f"Missing bind mount source: {name}/{source}")
    require(services['db-init'].get('profiles') == ['seed'], 'Seed data must be opt-in')
    require(services['whatsapp-service'].get('profiles') == ['whatsapp'], 'WhatsApp must be opt-in')
    require('backend' in services['db-init']['depends_on'], 'Seed job must wait for backend')
    require(not (ROOT / 'mongodb/pwfile').exists(), 'MongoDB password file must not be published')
    for name in ('ADMIN_PASSWORD', 'JWT_SECRET', 'EMAIL_ENCRYPTION_KEY'):
        tree = ast.parse((ROOT / 'apps/admin-backend/app.py').read_text())
        assignments = {n.targets[0].id: n.value for n in tree.body
                       if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
        require(isinstance(assignments.get(name), ast.Subscript),
                f"Backend must require an explicit {name}")
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Publication checks passed: source syntax, secret patterns, localization, Compose and build contexts.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
