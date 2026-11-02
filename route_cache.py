"""Versioned, checksummed routing cache for unchanged channel geometry."""
from functools import lru_cache
import gzip
import hashlib
import json
import os
from pathlib import Path

from logic_gates import Circuit
from router import route


@lru_cache(maxsize=1)
def version():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256(b'route-cache-schema-1')
    for name in ('router.py','redstone_geometry.py','route_cache.py'):
        digest.update((root/name).read_bytes())
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'))


def encode(circuit):
    return {'size':[circuit.size_x,circuit.size_y,circuit.size_z],
            # Preserve insertion order as well as values: downstream graph
            # traversal can use that order to break equivalent-placement ties.
            'blocks':[[list(p),b] for p,b in circuit.blocks.items()],
            'wires':[[[list(p),d] for p,d in net.items()] for net in circuit.net_wires],
            'pins':circuit.net_pins,'air':sorted(circuit.required_air),
            'repeaters':sorted(circuit.routing_repeaters),
            'stats':{k:v for k,v in circuit.route_stats.items() if k not in ('seconds','cached')}}


def decode(body):
    circuit = Circuit(*body['size'])
    circuit.blocks = {tuple(p):b for p,b in body['blocks']}
    circuit.net_wires = [{tuple(p):tuple(d) if d is not None else None for p,d in net}
                         for net in body['wires']]
    circuit.net_pins = [[tuple(p) for p in net] for net in body['pins']]
    circuit.required_air = {tuple(p) for p in body['air']}
    circuit.routing_repeaters = {tuple(p) for p in body['repeaters']}
    circuit.route_stats = dict(body['stats'],cached=True)
    return circuit


def cached_route(nets,min_width,pin_headroom=(),directory=None):
    directory = Path(directory or os.environ.get('ROUTER_CACHE_DIR') or
                     Path(__file__).resolve().parent/'.cache'/'router')
    request = {'version':version(),'nets':nets,'width':min_width,'air':sorted(pin_headroom)}
    key = hashlib.sha256(canonical(request).encode()).hexdigest()
    path = directory/f'{key}.json.gz'
    try:
        with gzip.open(path,'rt') as handle:
            entry = json.load(handle)
        body = entry['body']
        if entry['key'] == key and entry['checksum'] == hashlib.sha256(canonical(body).encode()).hexdigest():
            return decode(body)
    except (OSError,EOFError,ValueError,KeyError,TypeError):
        pass
    circuit = route(nets,min_width=min_width,pin_headroom=pin_headroom)
    circuit.route_stats['cached'] = False
    body = encode(circuit)
    entry = {'key':key,'checksum':hashlib.sha256(canonical(body).encode()).hexdigest(),'body':body}
    temporary = directory/f'{key}.{os.getpid()}.tmp'
    try:
        directory.mkdir(parents=True,exist_ok=True)
        with gzip.open(temporary,'wt') as handle:
            json.dump(entry,handle,separators=(',',':'))
        temporary.replace(path)
    except OSError:
        # A read-only/full cache must never stop successful circuit generation.
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return circuit
