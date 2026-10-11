"""Install records of EXPERIMENTAL .avrgame packages, and the one reader of them (AVR-39).

NOT an SDK, NOT stable. An installed package leaves one root-owned, world-readable, secret-free
JSON file, `<records dir>/<id>.json` (default /etc/avrana-party/packages.d), that says what was
installed and what the appliance made of it:

    {"record": "avrana.avrgame-install/experimental.1",
     "id", "version", "sha256" (of the archive), "format", "installed_at",
     "root": "/opt/avrana-games/<id>/<version>-<sha12>",     # the staged, root-owned tree
     "files": [{"path", "size", "sha256"}, ...],              # what `verify` checks
     "contract": {...the validated embedded Game Contract...},
     "grant": {"game", "entry": "/games/<id>/", "tier": "community", "permissions_granted": [...],
               "runtime": {"command": [interpreter, args...], "working_directory": root}},
     "package": {publisher/license/source: UNVERIFIED claims from the package}}

Party Core, provisioning and the catalog read this directory as an overlay on the repository's
`contracts/games/` and `contracts/appliances/<id>.json`: `load` returns the contracts and grants
of the installed games. A record is NEVER trusted because root wrote it. Every record is checked
again, whole, on every load: its contract with the existing Game Contract validator, its grant
against the appliance grant rules, its tier, entry path, working directory and interpreter against
what an installer can have produced, and its id against the repository's first-party games. A
record that fails is refused by itself, with a named problem; the other records and the
repository's games are not affected. Nothing here imports, executes or evaluates package content.

Standard library only; imports on any OS.
"""
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from avrana.contracts import appliance, game, strictjson, vocabulary

from .common import FORMAT, MAX_FILES, MAX_FILE_BYTES, MANIFEST_NAME, check_json_depth, name_problem, text_ok
from .manifest import INTERPRETERS, MAX_ARG, MAX_ARGS, VERSION, module_form

RECORD = 'avrana.avrgame-install/experimental.1'
DEFAULT_RECORDS_DIR = '/etc/avrana-party/packages.d'
DEFAULT_GAMES_ROOT = '/opt/avrana-games'
# Who must own a record and its directory when a reader enforces it. Party Core runs as an
# unprivileged user and trusts only what root wrote; a test on a scratch directory sets this to None.
EXPECTED_OWNER = 0 if os.name == 'posix' else None
_DEFAULT = object()
TIER = 'community'            # the only tier a package can ever have; nothing in a package changes it
# What the package sandbox really provides, whatever was granted (AVR-336). `party_roster`: Party Core
# puts the roster (participant, name, role) in every game's launch. `persistent_storage`: the template
# unit gives every game a StateDirectory=. Every other permission is unobtainable in the sandbox (the
# unit has AF_UNIX only and PrivateDevices=), so a grant of one would be a record that says more than
# is true. Party Core does not enforce grants at launch (docs/design/AVRGAME-PACKAGE.md).
GRANTABLE = ('persistent_storage', 'party_roster')
ALWAYS_PROVIDED = 'party_roster'    # delivered to every game, so a package must request it and be granted it
MAX_RECORD_BYTES = 2 * 1024 * 1024
TOP = ('record', 'id', 'version', 'sha256', 'format', 'installed_at', 'root', 'files', 'contract',
       'grant', 'package')
REQUIRED = tuple(k for k in TOP if k != 'installed_at')
SHA256 = re.compile(r'^[0-9a-f]{64}\Z')
STAMP = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z')
CLAIMS = ('publisher', 'license', 'source')


class RecordError(ValueError):
    """One record is not acceptable. `problems` lists every reason."""

    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__('; '.join(self.problems))


@dataclass(frozen=True)
class Record:
    """A record that passed every check. `doc` is the parsed document."""
    id: str
    version: str
    sha256: str
    root: str
    files: tuple
    contract: dict
    grant: dict
    package: dict
    doc: dict = field(repr=False, default=None)

    @property
    def sha12(self):
        return self.sha256[:12]


@dataclass
class Loaded:
    """What a records directory holds. `problems` are `<id>: <reason>`, one per refused record or
    unexpected file; `refused` is the ids (from file names) whose record was refused."""
    records: dict = field(default_factory=dict)
    contracts: dict = field(default_factory=dict)
    grants: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    refused: frozenset = frozenset()


def tree_name(version, sha256):
    return f'{version}-{sha256[:12]}'


def tree_root(games_root, package_id, version, sha256):
    """The final staged tree of a package: <games root>/<id>/<version>-<sha12> (POSIX text)."""
    return str(PurePosixPath(str(games_root).replace('\\', '/')) / package_id / tree_name(version, sha256))


def entry_path(package_id):
    return f'/games/{package_id}/'


def build_grant(package, granted, root, interpreters=INTERPRETERS):
    """The appliance's grant for a package: community tier, the permissions the operator allowed
    (and the contract requested), and the command the template unit runs in the staged tree."""
    server = package.manifest['server']
    return {
        'game': package.id,
        'entry': entry_path(package.id),
        'tier': TIER,
        'permissions_granted': sorted(granted),
        'runtime': {'command': [interpreters[server['interpreter']], *server['args']],
                    'working_directory': root},
    }


def build_record(package, grant, root, installed_at=None):
    """The record document for `package` (a Package), its `grant` and staged `root`."""
    claims = package.manifest['package']
    doc = {
        'record': RECORD,
        'id': package.id,
        'version': package.version,
        'sha256': package.sha256,
        'format': package.manifest['format'],
        'root': root,
        'files': [{'path': f.path, 'size': f.size, 'sha256': f.sha256} for f in package.files],
        'contract': package.game,
        'grant': grant,
        'package': {k: claims[k] for k in CLAIMS if k in claims},
    }
    if installed_at:
        doc['installed_at'] = installed_at
    return doc


def dumps(doc):
    """The bytes written to disk: deterministic."""
    return (json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _files_problems(files, package_id):
    p = []
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        return [f'files: a list of 1-{MAX_FILES} entries']
    paths = []
    for i, item in enumerate(files):
        where = f'files[{i}]'
        if not isinstance(item, dict) or set(item) != {'path', 'size', 'sha256'}:
            p.append(f'{where}: an object with exactly path, size and sha256')
            continue
        why = name_problem(item['path'], where)
        if why:
            p.append(why)
        else:
            paths.append(item['path'])
        if type(item['size']) is not int or not 0 <= item['size'] <= MAX_FILE_BYTES:
            p.append(f'{where}.size: an integer 0-{MAX_FILE_BYTES}')
        if not isinstance(item['sha256'], str) or not SHA256.match(item['sha256']):
            p.append(f'{where}.sha256: 64 lowercase hex digits')
    if len(set(paths)) != len(paths):
        p.append('files: duplicate paths')
    if paths != sorted(paths):
        p.append('files: not sorted by path')
    if MANIFEST_NAME not in paths:
        p.append(f'files: {MANIFEST_NAME} is missing')
    return p


def _runtime_problems(grant, root, interpreters):
    p = appliance.runtime_problems(grant.get('runtime'), 'grant.runtime')
    if p:
        return p
    runtime = grant['runtime']
    if runtime['working_directory'] != root:
        p.append('grant.runtime.working_directory: must be the record\'s staged root')
    command = runtime['command']
    if command[0] not in interpreters.values():
        p.append(f'grant.runtime.command: the interpreter must be one of {sorted(interpreters.values())}')
    args = command[1:]
    if command[0] == INTERPRETERS.get('python3') and not module_form(args):
        p.append('grant.runtime.command: python3 runs only ["-m", "<module>", ...]')
    if not 1 <= len(args) <= MAX_ARGS:
        p.append(f'grant.runtime.command: 1-{MAX_ARGS} arguments after the interpreter')
    for i, arg in enumerate(args):
        if not text_ok(arg, 1, MAX_ARG) or arg.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', arg) \
                or '..' in arg.split('/'):
            p.append(f'grant.runtime.command[{i + 1}]: a package argument has no absolute path or ".."')
    return p


def validate_record(doc, name, repo_contracts, vocab=None, interpreters=INTERPRETERS, games_root=DEFAULT_GAMES_ROOT):
    """Check one parsed record found under the file name `name` (without `.json`) and return a
    Record, or raise RecordError listing every problem. Nothing the record says is believed.
    `games_root` is where staged trees live; the record's root must be exactly
    <games_root>/<id>/<version>-<sha12> (Party Core uses the module default, /opt/avrana-games)."""
    if not isinstance(doc, dict):
        raise RecordError('the record must be one JSON object')
    p = []
    for key in sorted(set(doc) - set(TOP)):
        p.append(f'unknown key {key!r}')
    for key in REQUIRED:
        if key not in doc:
            p.append(f'missing {key!r}')
    if p:
        raise RecordError(p)
    if doc['record'] != RECORD:
        p.append(f'record: this appliance reads only {RECORD!r}')
    pid = doc['id']
    if not isinstance(pid, str) or not game.ID.fullmatch(pid) or pid in game.RESERVED_IDS:
        raise RecordError(p + ['id: not a usable game id'])
    if pid != name:
        p.append(f'id {pid!r} does not match the file name {name}.json')
    if pid in repo_contracts:
        p.append(f'id: {pid!r} is a game of this repository; a package cannot shadow it')
    version = doc['version']
    if not isinstance(version, str) or not VERSION.match(version):
        p.append('version: like 1.2.3 or 1.2.3-rc.1')
    sha = doc['sha256']
    if not isinstance(sha, str) or not SHA256.match(sha):
        p.append('sha256: 64 lowercase hex digits')
    if doc['format'] != FORMAT:
        p.append(f'format: this appliance supports only {FORMAT!r}')
    if 'installed_at' in doc and (not isinstance(doc['installed_at'], str) or not STAMP.match(doc['installed_at'])):
        p.append('installed_at: YYYY-MM-DDTHH:MM:SSZ')
    root = doc['root']
    if not isinstance(root, str) or not root.startswith('/') or '\\' in root:
        p.append('root: an absolute POSIX path')
    elif not isinstance(version, str) or not isinstance(sha, str) or not SHA256.match(sha) \
            or root != tree_root(games_root, pid, version, sha):
        p.append(f'root: must be exactly {str(games_root).rstrip("/")}/<id>/<version>-<first 12 hex of sha256>')
    p += _files_problems(doc['files'], pid)

    contract = None
    try:
        contract = game.validate(doc['contract'], vocab if vocab is not None else vocabulary.load())
    except game.ContractError as exc:
        p += [f'contract: {x}' for x in exc.problems]
    except (TypeError, AttributeError):
        p.append('contract: must be an object')
    if contract is not None:
        if contract['id'] != pid:
            p.append(f'contract.id {contract["id"]!r} is not the record id')
        if contract['kind'] != 'native' or (contract['runtime']['type'], contract['runtime']['start']) != ('external', 'service'):
            p.append('contract: a package game is native, runtime external with start service')
        if 'package' in contract:
            p.append('contract.package: not allowed in an installed game')

    grant = doc['grant']
    if not isinstance(grant, dict) or set(grant) != {'game', 'entry', 'tier', 'permissions_granted', 'runtime'}:
        p.append('grant: an object with exactly game, entry, tier, permissions_granted and runtime')
    else:
        if grant['game'] != pid:
            p.append('grant.game: must be the record id')
        if grant['entry'] != entry_path(pid):
            p.append(f'grant.entry: must be {entry_path(pid)!r}')
        elif not appliance.PATH.match(grant['entry']) or grant['entry'].startswith(appliance.RESERVED_PREFIXES):
            p.append('grant.entry: not a usable entry path')
        if grant['tier'] != TIER:
            p.append(f'grant.tier: a package is always {TIER!r}')
        granted = grant['permissions_granted']
        if not isinstance(granted, list) or not all(isinstance(g, str) for g in granted) \
                or len(set(granted)) != len(granted):
            p.append('grant.permissions_granted: a list of unique permission names')
        elif contract is not None:
            extra = sorted(set(granted) - set(contract['runtime']['permissions']))
            if extra:
                p.append(f'grant.permissions_granted: {extra} were never requested by the contract')
            unobtainable = sorted(set(granted) - set(GRANTABLE))
            if unobtainable:
                p.append(f'grant.permissions_granted: {unobtainable} cannot be provided inside the package sandbox '
                         f'(only {", ".join(GRANTABLE)} can)')
            if ALWAYS_PROVIDED not in granted:
                p.append(f'grant.permissions_granted: {ALWAYS_PROVIDED} is delivered to every game at launch, '
                         'so a package record must carry it')
        if isinstance(root, str):
            p += _runtime_problems(grant, root, interpreters)
    claims = doc['package']
    if not isinstance(claims, dict) or set(claims) - set(CLAIMS) or not {'publisher', 'license'} <= set(claims) \
            or not all(text_ok(v, 1, 200) for v in claims.values()):
        p.append('package: publisher and license (and optionally source), printable text; display-only claims')
    if p:
        raise RecordError(p)
    return Record(id=pid, version=version, sha256=sha, root=root,
                  files=tuple((f['path'], f['size'], f['sha256']) for f in doc['files']),
                  contract=contract, grant=grant, package=dict(claims), doc=doc)


def _owner(owner):
    return EXPECTED_OWNER if owner is _DEFAULT else owner


def read_record_file(path, name, repo_contracts, vocab=None, interpreters=INTERPRETERS, strict_modes=None,
                     games_root=DEFAULT_GAMES_ROOT, owner=_DEFAULT):
    """Read, parse strictly and validate one record file. A symbolic link, a non-file, a file that
    is group- or world-writable (POSIX), one not owned by `owner` (default: root on POSIX; None
    skips the check), an oversized or too deeply nested file or malformed JSON is a RecordError."""
    if strict_modes is None:
        strict_modes = os.name == 'posix'
    owner = _owner(owner)
    try:
        st = os.lstat(path)
    except OSError:
        raise RecordError('cannot be examined') from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise RecordError('not a regular file')
    if owner is not None and st.st_uid != owner:
        raise RecordError(f'not owned by uid {owner}')
    if strict_modes and st.st_mode & 0o022:
        raise RecordError('writable by a group or others')
    if st.st_size > MAX_RECORD_BYTES:
        raise RecordError(f'larger than {MAX_RECORD_BYTES} bytes')
    try:
        with open(path, 'rb') as f:
            text = f.read(MAX_RECORD_BYTES + 1).decode('utf-8')
        check_json_depth(text)
        doc = strictjson.loads(text)
    except (OSError, UnicodeDecodeError):
        raise RecordError('cannot be read as UTF-8 text') from None
    except (ValueError, RecursionError) as exc:
        raise RecordError(f'not strict JSON ({str(exc)[:80]})') from None
    return validate_record(doc, name, repo_contracts, vocab, interpreters, games_root)


def directory_problem(directory, owner=_DEFAULT, strict_modes=None):
    """Why a records directory cannot be believed, or None: a symbolic link, not owned by `owner`,
    or writable by a group or others. Whoever can write there can make Party Core run a game."""
    if strict_modes is None:
        strict_modes = os.name == 'posix'
    owner = _owner(owner)
    try:
        st = os.lstat(directory)
    except OSError:
        return 'cannot be examined'
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return 'not a plain directory'
    if owner is not None and st.st_uid != owner:
        return f'not owned by uid {owner}'
    if strict_modes and st.st_mode & 0o022:
        return 'writable by a group or others'
    return None


def load(directory, repo_contracts, vocab=None, interpreters=INTERPRETERS, strict_modes=None,
         games_root=DEFAULT_GAMES_ROOT, owner=_DEFAULT):
    """Every valid record of `directory`, as the contracts and grants they add to the repository's.
    A missing directory is nothing installed. A record that is refused (or a stray file) is listed
    in `problems` and affects nothing else; a directory that cannot be believed refuses every record
    in it. Hidden files (an installer's temporary file) are ignored."""
    out = Loaded()
    if not directory or not os.path.isdir(directory):
        return out
    refused = set()
    vocab = vocab if vocab is not None else vocabulary.load()
    try:
        names = sorted(os.listdir(directory))
    except OSError as exc:
        out.problems.append(f'(records directory): cannot be listed ({type(exc).__name__})')
        return out
    bad_directory = directory_problem(directory, owner, strict_modes)
    if bad_directory:
        out.problems.append(f'(records directory) {directory}: {bad_directory}; none of its records is used')
    for filename in names:
        if filename.startswith('.'):
            continue
        name = filename[:-5] if filename.endswith('.json') else None
        if name is None or not game.ID.fullmatch(name):
            out.problems.append(f'{filename}: not an install record (<id>.json)')
            continue
        if bad_directory:
            refused.add(name)
            continue
        try:
            record = read_record_file(os.path.join(directory, filename), name, repo_contracts, vocab,
                                      interpreters, strict_modes, games_root, owner)
        except RecordError as exc:
            refused.add(name)
            out.problems += [f'{name}: record refused: {x}' for x in exc.problems]
            continue
        out.records[record.id] = record
        out.contracts[record.id] = record.contract
        out.grants[record.id] = record.grant
    out.refused = frozenset(refused)
    return out


def overlay(repo_contracts, directory, **kw):
    """(contracts, grants, problems): the repository's contracts plus the installed games', and the
    installed games' grants. For callers that want one merged mapping."""
    found = load(directory, repo_contracts, **kw)
    return {**repo_contracts, **found.contracts}, found.grants, found.problems
