#!/usr/bin/env python3
"""Offline repository governance checks. Never prints file contents or contacts the Pi."""
import argparse
from datetime import date
import fnmatch
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CLASSES = {'canonical', 'decision', 'design', 'strategy', 'runbook', 'evidence',
           'research', 'historical', 'archived'}
STATUSES = {'current', 'accepted', 'implemented', 'mixed', 'proposed', 'experimental',
            'historical', 'archived', 'research'}
AUTHORITIES = {'reference', 'scoped-contract', 'accepted-portions', 'strategic-direction',
               'procedure', 'historical-observation', 'none', 'entry-point-only'}
REQUIRED = {'AGENTS.md': ('canonical', 'agent-invariants'),
            'README.md': ('canonical', 'project-overview'),
            'CONTRIBUTING.md': ('canonical', 'contribution-workflow'),
            'docs/README.md': ('canonical', 'documentation-map'),
            'docs/SYSTEM.md': ('canonical', 'deployed-state'),
            'docs/TESTING.md': ('canonical', 'verification'),
            'docs/ROADMAP.md': ('strategy', 'strategic-direction'),
            'docs/design/README.md': ('canonical', 'design-index')}
GENERATED_CHECKS = {'ui', 'catalog', 'cross-repo'}


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('non-finite JSON number')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=invalid)


def repo_files(root):
    result = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others',
                             '--exclude-standard'], cwd=root, check=True, capture_output=True)
    return {p for p in result.stdout.decode('utf-8').split('\0')
            if p and (root / p).is_file()}


def valid_date(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def safe_path(value):
    return (isinstance(value, str) and bool(value) and '\\' not in value and ':' not in value
            and not PurePosixPath(value).is_absolute() and '..' not in PurePosixPath(value).parts)


def prose(text):
    """Remove code while preserving line numbers. Fenced examples are not links/instructions."""
    lines, fence = [], None
    for line in text.splitlines():
        mark = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if mark:
            if fence is None:
                fence = mark[1]
            elif mark[1][0] == fence[0] and len(mark[1]) >= len(fence):
                fence = None
            lines.append('')
        elif fence or line.startswith('    ') or line.startswith('\t'):
            lines.append('')
        else:
            lines.append(re.sub(r'(`+).*?\1', '', line))
    return '\n'.join(lines)


def anchors(text):
    result, counts = set(), {}
    # Heading inline code contributes to GitHub's slug; remove delimiters, not its content.
    for line in text.splitlines():
        match = re.match(r'^#{1,6}\s+(.+?)(?:\s+#+)?$', line)
        if match:
            title = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', match[1])
            title = re.sub(r'<[^>]*>', '', title).lower().replace('`', '')
            slug = ''.join(c for c in title if c.isalnum() or c in '_- ')
            slug = slug.replace(' ', '-')
            n = counts.get(slug, 0)
            counts[slug] = n + 1
            result.add(slug + (f'-{n}' if n else ''))
    result.update(re.findall(r'\b(?:id|name)=["\']([^"\']+)["\']', text))
    return result


def markdown_links(text):
    """Yield (line, destination) for supported Markdown and HTML links."""
    text = prose(text)
    destination = r'(?:<([^>]+)>|([^\s]+?))'
    inline = re.compile(r'!?\[(?:[^\]\\]|\\.)*\]\(\s*' + destination
                        + r'(?:\s+["\'][^\n]*?["\'])?\s*\)')
    definitions = {}
    for match in re.finditer(r'^\s{0,3}\[([^]]+)\]:\s*' + destination + r'(?:\s|$)', text, re.M):
        definitions[' '.join(match[1].lower().split())] = match[2] or match[3]
        yield text.count('\n', 0, match.start()) + 1, match[2] or match[3]
    for match in inline.finditer(text):
        yield text.count('\n', 0, match.start()) + 1, match[1] or match[2]
    for match in re.finditer(r'!?\[([^]\n]+)\]\[([^]\n]*)\]', text):
        key = ' '.join((match[2] or match[1]).lower().split())
        yield text.count('\n', 0, match.start()) + 1, definitions.get(key)
    for match in re.finditer(r'<(?:a|img)\b[^>]*?\b(?:href|src)=["\']([^"\']+)', text, re.I):
        yield text.count('\n', 0, match.start()) + 1, match[1]


def check_repository(root, files):
    errors = []
    def fail(path, rule):
        errors.append(f'{path}: {rule}')
    def exists(path):
        if not safe_path(path):
            return False
        target = (root / path).resolve()
        return target.is_relative_to(root.resolve()) and target.exists()
    try:
        manifest = strict_json(root / 'docs/manifest.json')
        if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
            raise ValueError('schema')
        if not all(isinstance(manifest.get(k), list) for k in
                   ['documents', 'generated', 'root_entries', 'external_authorities']):
            raise ValueError('fields')
    except (OSError, ValueError, TypeError):
        return ['docs/manifest.json: invalid manifest JSON/schema']

    external = manifest['external_authorities']
    expected_external = [
        {'name': 'Linear', 'url': 'https://linear.app/avranakern', 'canonical_for': 'live-work'},
        {'name': 'GitHub main', 'url': 'https://github.com/rcnechamkin/avrana-party/tree/main',
         'canonical_for': 'current-source'}]
    if external != expected_external:
        fail('docs/manifest.json', 'external authority boundary changed')
    domains = {'live-work', 'current-source'}
    documents = {}
    for entry in manifest['documents']:
        if (not isinstance(entry, dict) or not exists(entry.get('path'))
                or not (root / entry['path']).is_file()):
            fail('docs/manifest.json', 'document path missing or unsafe')
            continue
        path = entry['path']
        if path in documents or path not in files or not path.endswith('.md'):
            fail(path, 'duplicate/untracked/non-Markdown manifest document')
        documents[path] = entry
        cls, status, auth = (entry.get(k) for k in ['class', 'status', 'authority'])
        if not all(isinstance(value, str) for value in [cls, status, auth]):
            fail(path, 'class/status/authority must be strings')
            continue
        if cls not in CLASSES or status not in STATUSES or auth not in AUTHORITIES:
            fail(path, 'unknown class/status/authority')
        expected_authorities = {
            'canonical': {'reference', 'entry-point-only'}, 'decision': {'accepted-portions'},
            'strategy': {'strategic-direction'}, 'runbook': {'procedure'},
            'design': {'scoped-contract', 'none'},
        }
        if cls in expected_authorities and auth not in expected_authorities[cls]:
            fail(path, 'authority incompatible with document class')
        domain = entry.get('canonical_for')
        if domain is not None:
            if not isinstance(domain, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', domain):
                fail(path, 'invalid authority domain')
            elif domain in domains:
                fail(path, 'duplicate or forbidden authority domain')
            else:
                domains.add(domain)
        if cls in {'historical', 'archived', 'research', 'evidence'}:
            expected = 'historical-observation' if cls == 'evidence' else 'none'
            if auth != expected or domain is not None:
                fail(path, 'non-authoritative class gained authority')
        if status in {'proposed', 'experimental'} and (domain or auth not in {'none', 'procedure'}):
            fail(path, 'proposal/experiment gained contract authority')
        if '/archive/' in path and (cls not in {'historical', 'archived'} or status not in {'historical', 'archived'}):
            fail(path, 'archive namespace must remain historical/archived')
        if path.startswith('docs/research/') and cls != 'research':
            fail(path, 'research namespace must remain research')
        if path.startswith('docs/adr/') and cls != 'decision':
            fail(path, 'ADR must be classified as a decision')
        if path.startswith('docs/findings/'):
            if cls != 'evidence' or status != 'historical' or not valid_date(Path(path).name[:10]) or not re.match(r'\d{4}-\d{2}-\d{2}-.+\.md$', Path(path).name):
                fail(path, 'finding needs dated evidence classification')
            if entry.get('observed') != Path(path).name[:10]:
                fail(path, 'finding date must match filename')
        for field in ['observed', 'date']:
            if field in entry and not valid_date(entry[field]):
                fail(path, 'invalid ISO date metadata')
        text = (root / path).read_text(encoding='utf-8')
        marker = entry.get('status_marker')
        if cls == 'decision' and not marker:
            fail(path, 'ADR requires an explicit status marker')
        if marker is not None and (not isinstance(marker, str) or not marker or marker not in text.splitlines()[:20]):
            fail(path, 'status marker missing/changed; review manifest classification')
    for path in sorted(p for p in files if p.endswith('.md')):
        if path not in documents:
            fail(path, 'Markdown document missing from manifest')
    for path, (cls, domain) in REQUIRED.items():
        entry = documents.get(path, {})
        if entry.get('class') != cls or entry.get('canonical_for') != domain or entry.get('status') != 'current':
            fail(path, 'required canonical role missing/changed')

    allowed = manifest['root_entries']
    if any(not isinstance(p, str) or '/' in p or not safe_path(p) for p in allowed):
        fail('docs/manifest.json', 'invalid root allowlist')
    elif len(set(allowed)) != len(allowed):
        fail('docs/manifest.json', 'duplicate root allowlist entry')
    for path in files:
        if path.split('/')[0] not in allowed:
            fail(path, 'unexpected root entry; document intentional structure')
        if '/' not in path and 'handoff' in path.lower() and path != 'CODEX-HANDOFF.md':
            fail(path, 'root handoff logs belong in docs/archive/handoffs')
    for path in ['CLAUDE.md', 'CODEX-HANDOFF.md', 'docs/agents/claude-cloud.md']:
        if path not in documents:
            fail(path, 'agent compatibility layer missing')
            continue
        text = (root / path).read_text(encoding='utf-8')
        if 'AGENTS.md)' not in text or len(text.splitlines()) > 40 or documents[path].get('authority') != 'entry-point-only':
            fail(path, 'agent layer must be brief and defer to AGENTS')

    generated = set()
    attrs = (root / '.gitattributes').read_text(encoding='utf-8') if exists('.gitattributes') else ''
    for group in manifest['generated']:
        if not isinstance(group, dict) or not all(isinstance(group.get(k), list) and group[k] for k in ['paths', 'sources']):
            fail('docs/manifest.json', 'invalid generated mapping')
            continue
        if not isinstance(group.get('check'), str) or group['check'] not in GENERATED_CHECKS or not all(isinstance(group.get(k), str) and group[k] for k in ['regenerate', 'freshness']):
            fail('docs/manifest.json', 'generated group needs known check and regeneration command')
        for source in group['sources']:
            if not exists(source):
                fail('docs/manifest.json', 'generated source missing/unsafe')
        for pattern in group['paths']:
            if not safe_path(pattern):
                fail('docs/manifest.json', 'unsafe generated pattern')
                continue
            matched = {p for p in files if fnmatch.fnmatchcase(p, pattern)}
            if not matched or generated & matched:
                fail(pattern, 'generated pattern empty or overlaps another group')
            generated.update(matched)
            if f'{pattern} linguist-generated=true' not in attrs:
                fail(pattern, 'missing GitHub generated annotation')
        if group.get('check') == 'cross-repo' and not all(group.get(k) for k in ['source_repository', 'source_paths', 'freshness']):
            fail('docs/manifest.json', 'imported snapshot needs external provenance/check')
    if 'assets/vendor/** linguist-vendored=true' not in attrs:
        fail('.gitattributes', 'vendor annotation missing')
    required_outputs = {'web/party/styles.css', 'web/party/lib/icons.js',
                        'web/party/lib/avatars.js', 'web/party/catalog.json',
                        'contracts/catalogs/lan-games.json'}
    required_outputs.update(p for p in files if p.startswith(('web/party/avatars/',
                            'web/party/art/', 'assets/vendor/lan-games-art/')) and p.endswith('.svg'))
    if not required_outputs <= generated:
        fail('docs/manifest.json', 'known generated output missing from provenance map')

    for path in sorted(files):
        if path in generated or path.startswith('assets/vendor/') or (root / path).stat().st_size > 1024 * 1024:
            continue
        try:
            text = (root / path).read_text(encoding='utf-8')
        except (UnicodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if re.match(r'^(?:<{7}(?: |$)|={7}$|>{7}(?: |$)|\|{7}(?: |$))', line):
                fail(f'{path}:{number}', 'conflict marker')
        if not path.endswith('.md'):
            continue
        for number, target in markdown_links(text):
            location = f'{path}:{number}'
            if target is None:
                fail(location, 'undefined reference link')
                continue
            try:
                parsed = urlsplit(target)
            except ValueError:
                fail(location, 'malformed link destination')
                continue
            if parsed.scheme or parsed.netloc:
                continue
            local = unquote(parsed.path)
            resolved = ((root / local.lstrip('/')) if local.startswith('/') else
                        (root / path).parent / local) if local else root / path
            resolved = resolved.resolve()
            if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                fail(location, 'relative link does not resolve within repository')
            elif parsed.fragment and resolved.suffix == '.md' and resolved.is_file():
                if unquote(parsed.fragment) not in anchors(resolved.read_text(encoding='utf-8')):
                    fail(location, 'Markdown heading fragment does not resolve')
    if exists('avrana-party.nginx') and exists('arcade/nginx-site'):
        if (root/'avrana-party.nginx').read_bytes() != (root/'arcade/nginx-site').read_bytes():
            fail('avrana-party.nginx', 'nginx copies differ')
    else:
        fail('avrana-party.nginx', 'nginx source pair missing')
    try:
        inventory = strict_json(root / 'docs/branches.json')
        if inventory.get('schema_version') != 1 or not valid_date(inventory.get('observed')) or not inventory.get('branches'):
            raise ValueError('branch schema')
        names = set()
        for branch in inventory['branches']:
            if (branch['name'] in names or branch['canonical'] is not False or
                    branch['wholesale_merge'] != 'forbidden' or branch['status'] != 'retained' or
                    not branch['purpose'] or not re.fullmatch(r'[0-9a-f]{40}', branch['observed_head'])):
                raise ValueError('branch boundary')
            names.add(branch['name'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        fail('docs/branches.json', 'invalid retained branch inventory')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated', action='store_true', help='also compose existing UI/catalog freshness checks')
    args = parser.parse_args()
    errors = check_repository(ROOT, repo_files(ROOT))
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(f'Repository integrity: {len(errors)} error(s)', file=sys.stderr)
        return 1
    print('Repository integrity: OK')
    if args.generated:
        # Fixed, reviewed commands: manifest strings are documentation, never executable input.
        for command in [['node', 'tools/check-ui.mjs'],
                        [sys.executable, '-m', 'avrana.contracts.catalog', '--check']]:
            result = subprocess.run(command, cwd=ROOT, check=False)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
