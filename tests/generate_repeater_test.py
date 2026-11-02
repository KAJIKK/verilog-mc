"""Parallel baseline/optimized live tests, including every wire and OFF edge."""
import argparse
import contextlib
import io
import itertools
import json
from pathlib import Path
import random

from redstone_geometry import FACING
from repeater_postprocessor import build_graph,build_graph_baseline,parse_state
from tests.benchmark_repeaters import load_corpus
from tests.generate_adder_test import fill_commands
from tests.live_test_runtime import install_chunk_lease


def add_drivers(fixture,blocks):
    """External repeaters give each source exactly 15, independent of direction."""
    drivers = []
    signals = set(p for net in fixture.nets for p in net)
    for source,_,_ in fixture.sources:
        for dx,dz in ((-1,0),(1,0),(0,-1),(0,1)):
            x,y,z = source
            driver,back = (x+dx,y,z+dz),(x+2*dx,y,z+2*dz)
            support = (driver[0],y-1,driver[2])
            if driver in blocks or back in blocks or support in signals:
                continue
            adjacent = [(back[0]+ox,back[1]+oy,back[2]+oz)
                        for ox,oy,oz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))]
            if any(p in signals for p in adjacent):
                continue
            blocks[driver] = f'minecraft:repeater[facing={FACING[-dx,-dz]}]'
            blocks[support] = 'minecraft:white_wool'
            drivers.append(back)
            # Reserve the OFF driver space while locating later drivers.
            blocks[back] = 'minecraft:air'
            break
        else:
            raise ValueError(f'No safe external source driver: {fixture.name} {source}')
    return drivers


def patterns(count):
    if count <= 4:
        inputs = list(itertools.product((0,1),repeat=count))
    else:
        rng = random.Random(684)
        inputs = [(1,)*count,*[tuple(int(i==j) for i in range(count)) for j in range(count)],
                  *[tuple(rng.randrange(2) for _ in range(count)) for _ in range(8)]]
    result = [(0,)*count]
    for values in inputs:
        if any(values):
            result.extend([values,(0,)*count])
    # Repeat the ON/OFF cycle even for one-source fixtures.
    result.extend([(1,)*count,(0,)*count])
    return result


def generate(corpus,destination,origin=(-1250,-60,200),namespace='rpt_stress'):
    placed,skipped = [],[]
    for f in load_corpus(corpus):
        if not f.nets:
            continue
        for variant,algorithm in (('baseline',build_graph_baseline),('optimized',build_graph)):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    _,repeaters = algorithm(f.blocks,f.sources)
            except ValueError as error:
                skipped.append(dict(name=f.name,variant=variant,error=str(error),expected=f.expected_error))
                continue
            if f.expected_error:
                raise ValueError(f'Expected impossible route was accepted: {f.name}')
            blocks = dict(f.blocks)
            blocks.update({p:f'minecraft:repeater[facing={d}]' for p,d in repeaters.items()})
            drivers = add_drivers(f,blocks)
            low = tuple(min(p[a] for p in blocks) for a in range(3))
            high = tuple(max(p[a] for p in blocks) for a in range(3))
            placed.append(dict(fixture=f,variant=variant,repeaters=repeaters,blocks=blocks,
                               drivers=drivers,low=low,high=high,patterns=patterns(len(f.sources))))
    # Shelf packing by decreasing depth keeps parallel test chunks compact.
    placed.sort(key=lambda f:-(f['high'][2]-f['low'][2]))
    width,x,z,shelf = 192,0,0,0
    for entry in placed:
        low,high = entry['low'],entry['high']
        dx,dz = high[0]-low[0]+5,high[2]-low[2]+5
        if x+dx > width:
            x,z,shelf = 0,z+shelf,0
        entry['offset'] = (origin[0]+x-low[0],origin[1],origin[2]+z-low[2])
        x,shelf = x+dx,max(shelf,dz)
    root = destination/namespace
    functions = root/'data'/namespace/'function'
    functions.mkdir(parents=True,exist_ok=True)
    (root/'pack.mcmeta').write_text(json.dumps({'pack':{'description':
        'Parallel repeater edge-case differential tests','min_format':[121,0],'max_format':[121,0]}})+'\n')
    def write(name,commands):
        (functions/f'{name}.mcfunction').write_text('\n'.join(commands)+'\n')
    def pos(p,entry):
        return ' '.join(str(a+b) for a,b in zip(p,entry['offset']))
    placement = []
    lows,highs = [],[]
    for entry in placed:
        low,high,offset = entry['low'],entry['high'],entry['offset']
        low = (low[0],low[1]-1,low[2])
        high = (high[0],high[1]+1,high[2])
        placement += fill_commands(low,high,offset)
        placement += fill_commands(low,(high[0],low[1],high[2]),offset,'minecraft:stone_bricks')
        order = sorted(entry['blocks'].items(),key=lambda item:(
            2 if 'wire' in item[1] else 1 if 'repeater' in item[1] else 0,-item[0][1]))
        placement += [f'setblock {pos(p,entry)} {block}' for p,block in order if block != 'minecraft:air']
        lows.append(tuple(a+b for a,b in zip(low,offset)))
        highs.append(tuple(a+b for a,b in zip(high,offset)))
    low = tuple(min(p[a] for p in lows) for a in range(3))
    high = tuple(max(p[a] for p in highs) for a in range(3))
    low = (low[0]-2,low[1],low[2]-2)
    high = (high[0]+2,high[1]+1,high[2]+2)
    # Clear between shelves too: repacking a prior suite must not leave stray
    # powered wires in a new fixture's gutter. A continuous base aids inspection.
    placement = (fill_commands(low,high,(0,0,0))+
                 fill_commands(low,(high[0],low[1],high[2]),(0,0,0),'minecraft:stone_bricks')+
                 placement)
    chunks = install_chunk_lease(write,namespace,low,high)
    batches = [placement[i:i+8000] for i in range(0,len(placement),8000)]
    write('place',[f'function {namespace}:load',f'data modify storage {namespace}:results placement set value "running"',
                   f'function {namespace}:place_0'])
    for i,batch in enumerate(batches):
        following = ([f'schedule function {namespace}:place_{i+1} 1t replace'] if i+1 < len(batches)
                     else [f'data modify storage {namespace}:results placement set value "complete"'])
        write(f'place_{i}',batch+following)
    steps = max(len(f['patterns']) for f in placed)
    # Sum of repeaters is a conservative series-delay bound. Include turn-off
    # propagation and a margin; no reference-dependent early success shortcut.
    settle = max(24,4*max(sum('repeater' in s for s in f['blocks'].values()) for f in placed)+12)
    objective = namespace
    start = [f'function {namespace}:load',f'scoreboard objectives add {objective} dummy',
             f'data modify storage {namespace}:results status set value "running"',
             f'data modify storage {namespace}:results failures set value []']
    start += [f'scoreboard players set #{variant}_{kind} {objective} 0'
              for variant in ('b','o') for kind in ('pass','fail')]
    start += [f'schedule clear {namespace}:check_{i}' for i in range(steps)]
    write('start',start+[f'function {namespace}:apply_0'])
    for step in range(steps):
        apply,check = [],[]
        for index,entry in enumerate(placed):
            if step >= len(entry['patterns']):
                continue
            f,values = entry['fixture'],entry['patterns'][step]
            apply += [f'setblock {pos(p,entry)} '+('minecraft:redstone_block' if v else 'minecraft:air')
                      for p,v in zip(entry['drivers'],values)]
            commands = [f'scoreboard players set #ok {objective} 1']
            for net in f.nets:
                on = any(value and source in net for (source,_,_),value in zip(f.sources,values))
                for p in net:
                    state = entry['blocks'][p]
                    if 'repeater' in state:
                        commands.append(f'execute unless block {pos(p,entry)} minecraft:repeater[powered={str(on).lower()}] run scoreboard players set #ok {objective} 0')
                    elif on:
                        commands += [f'execute unless block {pos(p,entry)} minecraft:redstone_wire run scoreboard players set #ok {objective} 0',
                                     f'execute if block {pos(p,entry)} minecraft:redstone_wire[power=0] run scoreboard players set #ok {objective} 0']
                    else:
                        commands.append(f'execute unless block {pos(p,entry)} minecraft:redstone_wire[power=0] run scoreboard players set #ok {objective} 0')
            key = 'b' if entry['variant'] == 'baseline' else 'o'
            failure = json.dumps(dict(name=f.name,variant=entry['variant'],step=step,inputs=values))
            commands += [f'execute if score #ok {objective} matches 1 run scoreboard players add #{key}_pass {objective} 1',
                         f'execute if score #ok {objective} matches 0 run scoreboard players add #{key}_fail {objective} 1',
                         f'execute if score #ok {objective} matches 0 run data modify storage {namespace}:results failures append value {failure}']
            write(f'check_{step}_{index}',commands)
            check.append(f'function {namespace}:check_{step}_{index}')
        write(f'apply_{step}',apply+[f'schedule function {namespace}:check_{step} {settle}t replace'])
        write(f'check_{step}',check+[f'function {namespace}:apply_{step+1}' if step+1 < steps else f'function {namespace}:finish'])
    finish = [f'data modify storage {namespace}:results status set value "complete"',f'function {namespace}:unload']
    finish += [f'execute store result storage {namespace}:results {variant}_{kind} int 1 run scoreboard players get #{key}_{kind} {objective}'
               for key,variant in (('b','baseline'),('o','optimized')) for kind in ('pass','fail')]
    write('finish',finish)
    write('stop',[f'schedule clear {namespace}:check_{i}' for i in range(steps)]+
          [f'function {namespace}:unload',f'data modify storage {namespace}:results status set value "stopped"'])
    # A separate geometry audit can run after tests without re-placing anything.
    # Ignore transient dust power/connections and repeater powered/locked state.
    audit,audit_blocks = [],0
    for entry in placed:
        for p,state in entry['blocks'].items():
            bid,props = parse_state(state)
            if bid == 'minecraft:air':
                continue
            audit_blocks += 1
            expected = bid+(f'[facing={props["facing"]}]' if bid == 'minecraft:repeater' else '')
            location = pos(p,entry)
            failure = json.dumps(dict(name=entry['fixture'].name,variant=entry['variant'],
                                      position=location,expected=expected))
            condition = f'execute if loaded {location} unless block {location} {expected}'
            audit += [f'execute unless loaded {location} run scoreboard players add #unloaded {objective} 1',
                      f'{condition} run scoreboard players add #missing {objective} 1',
                      f'{condition} if score #missing {objective} matches ..16 run data modify storage {namespace}:audit mismatches append value {failure}']
    audit_batches = [audit[i:i+4000] for i in range(0,len(audit),4000)]
    write('audit',[f'function {namespace}:load',f'scoreboard objectives add {objective} dummy',
                   f'scoreboard players set #missing {objective} 0',
                   f'scoreboard players set #unloaded {objective} 0',
                   f'data merge storage {namespace}:audit '+json.dumps(
                       dict(status='running',expected_blocks=audit_blocks,missing=0,unloaded=0,mismatches=[])),
                   f'schedule function {namespace}:audit_0 20t replace'])
    for i,batch in enumerate(audit_batches):
        following = ([f'schedule function {namespace}:audit_{i+1} 1t replace'] if i+1 < len(audit_batches)
                     else [f'execute store result storage {namespace}:audit missing int 1 run scoreboard players get #missing {objective}',
                           f'execute store result storage {namespace}:audit unloaded int 1 run scoreboard players get #unloaded {objective}',
                           f'data modify storage {namespace}:audit status set value "complete"',
                           f'function {namespace}:unload'])
        write(f'audit_{i}',batch+following)
    manifest = dict(origin=origin,bounds=[low,high],chunks=chunks,steps=steps,settle=settle,ticks=steps*settle,
                    audit_blocks=audit_blocks,
                    skipped=skipped,fixtures=[dict(name=e['fixture'].name,variant=e['variant'],offset=e['offset'],
                    repeaters=len(e['repeaters']),checks=len(e['patterns'])) for e in placed])
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k != 'fixtures'},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('datapacks',type=Path)
    parser.add_argument('--corpus',type=Path,default=Path('output/repeater_corpus.json.gz'))
    parser.add_argument('--origin',nargs=3,type=int,default=(-1250,-60,200))
    args = parser.parse_args()
    generate(args.corpus,args.datapacks,tuple(args.origin))
