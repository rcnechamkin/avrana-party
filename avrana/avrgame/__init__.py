"""EXPERIMENTAL `.avrgame` package format: manifest, validator, pack, read, extract.

NOT an SDK. NOT v0, stable or frozen: the format string is `avrana.avrgame/experimental.1`, every
name here may change, and the freeze gates (AVR-27 BLUFF review, Spades boundary validation, owner
acceptance) are unmet. Design and limits: docs/design/AVRGAME-PACKAGE.md. Evidence input:
docs/research/AVRGAME-EXPERIMENTAL-DRAFT.md. Standard library only (Python 3.10+).

A package is UNTRUSTED INPUT even when it validates ("valid is not trusted"). Nothing in this
library executes, imports or evaluates anything from a package; there are no install hooks. The
installer (a separate lane) decides what a valid package may do.

Public API
----------
FORMAT                       'avrana.avrgame/experimental.1'
INTERPRETERS                 read-only mapping, interpreter name -> absolute executable
                             ({'python3': '/usr/bin/python3'}); the appliance owns it
Refused(problems: list[str]) the one exception; `.problems` lists every reason
validate_manifest(obj, vocab=None) -> dict
                             normalised manifest {format, game, package, requires, server, client}
parse_manifest(data: bytes) -> object          strict JSON (duplicate keys refused)
supported_requires() -> {'session': (...), 'bridge': (...), 'result': (...)}
read(path) -> Package        validate a .avrgame file without extracting (alias: inspect)
extract(path, dest) -> Package   validate, then unpack into a new or empty directory
scan(data: bytes) -> (Package, zipfile.ZipFile)   validate archive bytes already in memory
pack(source_root, manifest_path, includes, out_path, compress=True) -> Package
load_recipe(path) -> Recipe, pack_recipe(recipe_path, out_path=None, compress=True) -> Package,
validate_recipe(recipe_path) -> Package        developer build recipe (avrgame.build.json)
Package(manifest, game, id, version, sha256, size, files, total_bytes, path)
PackageFile(path, size, sha256)
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_ARCHIVE_BYTES, MAX_MANIFEST_BYTES

CLI: python -m avrana.avrgame validate|pack|inspect (see __main__).
"""
from .archive import Package, PackageFile, extract, inspect, read, scan
from .build import (Recipe, build_bytes, load_recipe, pack, pack_recipe, recipe_build,
                    validate_recipe)
from .common import (FORMAT, MANIFEST_NAME, MAX_ARCHIVE_BYTES, MAX_FILE_BYTES, MAX_FILES,
                     MAX_MANIFEST_BYTES, MAX_TOTAL_BYTES, RECIPE_FORMAT, RECIPE_NAME, Refused)
from .manifest import INTERPRETERS, parse as parse_manifest, supported_requires, validate_manifest

__all__ = [
    'FORMAT', 'INTERPRETERS', 'MANIFEST_NAME', 'MAX_ARCHIVE_BYTES', 'MAX_FILES', 'MAX_FILE_BYTES',
    'MAX_MANIFEST_BYTES', 'MAX_TOTAL_BYTES', 'Package', 'PackageFile', 'RECIPE_FORMAT', 'RECIPE_NAME',
    'Recipe', 'Refused', 'build_bytes', 'extract', 'inspect', 'load_recipe', 'pack', 'pack_recipe',
    'parse_manifest', 'read', 'recipe_build', 'scan', 'supported_requires', 'validate_manifest',
    'validate_recipe',
]
