"""Generate live SR and toggle/reset tests using the imported library blocks."""
import argparse
import json
import random
from pathlib import Path
from tests.live_test_runtime import install_chunk_lease


ORIGINS = {'SR_LATCH': (-400, -60, 164), 'T_LATCH': (-390, -60, 164)}


def generate(destination, library=Path('gates.json')):
    gates = json.loads(library.read_text())
    root = destination / 'storage_test'
    functions = root / 'data/storage_test/function'
    functions.mkdir(parents=True, exist_ok=True)
    (root / 'pack.mcmeta').write_text(json.dumps({'pack': {
        'description': 'Live imported SR and T primitive characterization',
        'min_format': [121, 0], 'max_format': [121, 0]}}) + '\n')

    def write(name, commands):
        (functions / f'{name}.mcfunction').write_text('\n'.join(commands) + '\n')

    def pos(name, x, y, z):
        return ' '.join(str(a + b) for a, b in zip(ORIGINS[name], (x, y, z)))

    setup = []
    for name, origin in ORIGINS.items():
        gate = gates[name]
        setup += [f'fill {pos(name,-1,0,-2)} {pos(name,3,3,6)} air',
                  f'fill {pos(name,-1,-1,-2)} {pos(name,3,-1,6)} stone_bricks']
        # Install observer-facing drivers before the observer, avoiding a
        # construction-only reset pulse while its locking loop is settling.
        for x in gate['input_offsets'].values():
            setup.append(f'setblock {pos(name,x,0,-1)} repeater[facing=north]')
        # Place solid supports first, then components, then wires.
        items = sorted(gate['blocks'].items(), key=lambda item:
                       (('wire' in item[1]) * 2 + ('wool' not in item[1] and 'bulb' not in item[1])))
        setup += [f'setblock {pos(name,*map(int,coordinates.split(",")))} {block}'
                  for coordinates, block in items]
        for x in gate['output_offsets'].values():
            setup.append(f'setblock {pos(name,x,0,gate["size"][2]+2)} redstone_lamp')
            setup.append(f'setblock {pos(name,x,0,gate["size"][2]+1)} redstone_wire')
            setup.append(f'setblock {pos(name,x,0,gate["size"][2])} redstone_wire')
    low = (min(o[0]-1 for o in ORIGINS.values()),-61,min(o[2]-2 for o in ORIGINS.values()))
    high = (max(o[0]+3 for o in ORIGINS.values()),-57,max(o[2]+6 for o in ORIGINS.values()))
    install_chunk_lease(write,'storage_test',low,high)
    write('place',['function storage_test:load']+setup)

    steps = []
    def add(name, label, changes=None, expected=None, wait=40, category='normal'):
        steps.append(dict(name=name, label=label, changes=changes or {},
                          expected=expected, wait=wait, category=category))

    sr = 'SR_LATCH'
    add(sr, 'initialize reset', {'S': 0, 'R': 1}, 0)
    add(sr, 'release reset', {'R': 0}, 0)
    for previous in (0, 1):
        for s, r in ((0, 0), (1, 0), (0, 1)):
            add(sr, 'clear before preload', {'S': 0, 'R': 1}, 0)
            add(sr, 'release preload reset', {'R': 0}, 0)
            if previous:
                add(sr, 'preload one', {'S': 1}, 1)
                add(sr, 'release preload set', {'S': 0}, 1)
            add(sr, f'previous={previous},S={s},R={r}', {'S': s, 'R': r},
                1 if s else 0 if r else previous)
            add(sr, 'release inputs and retain', {'S': 0, 'R': 0},
                1 if s else 0 if r else previous, 1200)
    rng = random.Random(2026)
    q = 0
    add(sr, 'random init', {'S': 0, 'R': 1}, 0)
    add(sr, 'random init release', {'R': 0}, 0)
    for i in range(64):
        s, r = rng.choice(((0,0), (1,0), (0,1)))
        q = 1 if s else 0 if r else q
        add(sr, f'random legal SR state {i}', {'S': s, 'R': r}, q)
    # Record forbidden-input behavior without assuming deterministic release.
    add(sr, 'both SR inputs asserted', {'S': 1, 'R': 1}, None, category='characterization')
    add(sr, 'simultaneous SR release', {'S': 0, 'R': 0}, None, 200, 'characterization')
    add(sr, 'recover with set', {'S': 1}, 1)
    add(sr, 'hold recovered one', {'S': 0}, 1, 1200)
    add(sr, 'recover with reset', {'R': 1}, 0)
    add(sr, 'hold recovered zero', {'R': 0}, 0, 1200)

    t = 'T_LATCH'
    add(t, 'initialize inputs low', {'T': 0, 'R': 0}, None, 100)
    add(t, 'initialize with reset rising', {'R': 1}, 0)
    add(t, 'initialize with reset falling', {'R': 0}, 0)
    q = 0
    for width in (2, 4, 8, 20, 100, 1200):
        for cycle in range(2):
            q ^= 1
            add(t, f'toggle rise, pulse={width},cycle={cycle}', {'T': 1}, None, width,
                'pulse')
            add(t, f'toggle fall, pulse={width},cycle={cycle}', {'T': 0}, q, 60, 'pulse')
            add(t, f'hold after pulse={width},cycle={cycle}', expected=q, wait=100)
    for i in range(32):
        q ^= 1
        add(t, f'random toggle rise {i}', {'T': 1}, q, rng.choice((20,40,100)))
        add(t, f'random toggle fall {i}', {'T': 0}, q)
    add(t, 'set before reset test', {'T': 1}, 1)
    add(t, 'release toggle before reset', {'T': 0}, 1)
    add(t, 'reset rising edge', {'R': 1}, 0)
    add(t, 'hold reset high', expected=0, wait=1200)
    add(t, 'toggle with reset held high', {'T': 1}, 1, category='reset_characterization')
    add(t, 'release toggle with reset held high', {'T': 0}, 1, category='reset_characterization')
    add(t, 'reset falling edge', {'R': 0}, 0, category='reset_characterization')
    add(t, 'set for overlap test', {'T': 1}, 1)
    add(t, 'reset while toggle is high', {'R': 1}, 0, category='overlap')
    add(t, 'release toggle after overlapping reset', {'T': 0}, 0, category='overlap')
    add(t, 'release reset after overlap', {'R': 0}, 0, category='overlap')
    add(t, 'final toggle', {'T': 1}, 1)
    add(t, 'final retention', {'T': 0}, 1, 1200)

    write('start', [f'schedule clear storage_test:check_{i}' for i in range(len(steps))] + [
        'scoreboard objectives add storage_test dummy',
        'data modify storage storage_test:results entries set value []',
        'data modify storage storage_test:results failures set value []',
        'data modify storage storage_test:results status set value "running"',
        'function storage_test:place',
        'schedule function storage_test:apply_0 100t replace'])
    values = {name: {port: 0 for port in gates[name]['input_offsets']} for name in gates}
    total = 100
    for i, step in enumerate(steps):
        name = step['name']
        gate = gates[name]
        commands = []
        for port, value in step['changes'].items():
            x = gate['input_offsets'][port]
            values[name][port] = value
            commands.append(f'setblock {pos(name,x,0,-2)} ' + ('redstone_block' if value else 'air'))
        total += step['wait']
        write(f'apply_{i}', commands + [f'schedule function storage_test:check_{i} {step["wait"]}t replace'])
        entry = {k: step[k] for k in ('name','label','expected','category')}
        entry['inputs'] = values[name].copy()
        # SNBT has no null literal.
        if entry['expected'] is None:
            entry['expected'] = -1
        entry.update(actual=-1, complement=-1, passed=-1)
        commands = [f'data modify storage storage_test:results entries append value {json.dumps(entry)}',
                    'scoreboard players set #actual storage_test 0',
                    f'execute if block {pos(name,2,0,gate["size"][2]+2)} redstone_lamp[lit=true] run scoreboard players set #actual storage_test 1',
                    'execute store result storage storage_test:results entries[-1].actual int 1 run scoreboard players get #actual storage_test']
        if step['expected'] is not None:
            commands += ['scoreboard players set #ok storage_test 1',
                         f'execute unless score #actual storage_test matches {step["expected"]} run scoreboard players set #ok storage_test 0']
        if 'QN' in gate['output_offsets']:
            commands += ['scoreboard players set #inverse storage_test 0',
                         f'execute if block {pos(name,gate["output_offsets"]["QN"],0,gate["size"][2]+2)} redstone_lamp[lit=true] run scoreboard players set #inverse storage_test 1',
                         'execute store result storage storage_test:results entries[-1].complement int 1 run scoreboard players get #inverse storage_test']
            if step['expected'] is not None:
                commands.append(f'execute unless score #inverse storage_test matches {1-step["expected"]} run scoreboard players set #ok storage_test 0')
        if step['expected'] is not None:
            commands.append('execute store result storage storage_test:results entries[-1].passed int 1 run scoreboard players get #ok storage_test')
            commands.append('execute if score #ok storage_test matches 0 run data modify storage storage_test:results failures append from storage storage_test:results entries[-1]')
        commands.append(f'function storage_test:apply_{i+1}' if i+1 < len(steps) else 'function storage_test:finish')
        write(f'check_{i}', commands)
    finish = ['data modify storage storage_test:results status set value "complete"','function storage_test:unload']
    for name in ORIGINS:
        for result in ('passed', 'failed'):
            match = 1 if result == 'passed' else 0
            finish += ['data modify storage storage_test:results selected set value []',
                       f'data modify storage storage_test:results selected append from storage storage_test:results entries[{{name:"{name}",passed:{match}}}]',
                       f'execute store result storage storage_test:results {name}.{result} int 1 run data get storage storage_test:results selected']
    finish.append('data remove storage storage_test:results selected')
    write('finish', finish)
    print(json.dumps({'pack': str(root), 'steps': len(steps), 'ticks': total,
                      'origins': ORIGINS, 'sprint': f'tick sprint {total+200}t'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('datapacks', type=Path)
    args = parser.parse_args()
    generate(args.datapacks)
