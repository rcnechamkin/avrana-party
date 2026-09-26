"""Validate the small provider-specific catalog seam, separate from v0 grants."""
import re


def ps1(contract):
    meta = contract.get('extensions', {}).get('net.avrana.ps1')
    if not isinstance(meta, dict) or set(meta) - {'serial', 'stream_slots', 'multitap_port',
                                                 'multitap', 'metadataSource'}:
        raise ValueError('PS1: invalid metadata fields')
    serial, slots = meta.get('serial'), meta.get('stream_slots')
    if not isinstance(serial, str) or not re.fullmatch(r'S[A-Z]{3}-[0-9]{5}', serial):
        raise ValueError('PS1: disc serial required')
    if type(slots) is not int or not 1 <= slots <= 4 or slots != contract['input'].get('slots'):
        raise ValueError('PS1: stream slots must match contract input slots')
    if contract['runtime']['type'] != 'emulator_profile':
        raise ValueError('PS1: emulator profile required')
    if contract['id'] != 'ps1-' + contract['runtime']['profile']:
        raise ValueError('PS1: stable profile/id required')
    sources = meta.get('metadataSource')
    if not isinstance(sources, dict) or set(sources) != {'titleProfiles', 'manifest'}:
        raise ValueError('PS1: metadata sources required')
    for source in sources.values():
        if (not isinstance(source, dict) or set(source) != {'ref', 'commit'}
                or not isinstance(source['ref'], str)
                or not isinstance(source['commit'], str)
                or not re.fullmatch(r'[0-9a-f]{40}', source['commit'])):
            raise ValueError('PS1: source commit/ref required')
    if contract['input']['model'] == 'hotseat':
        if slots != 1 or meta.get('multitap') != 'disabled':
            raise ValueError('PS1: hotseat uses one controller, no multitap')
    elif contract['input']['model'] == 'controller_slots':
        if type(meta.get('multitap_port')) is not int or meta['multitap_port'] != 2:
            raise ValueError('PS1: audited Bomberman multitap is port 2')
    else:
        raise ValueError('PS1: unsupported input model')
    return {'profile': contract['runtime']['profile'], 'serial': serial, 'streamSlots': slots}
