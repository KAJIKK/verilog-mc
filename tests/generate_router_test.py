"""Generate progressively harder live routing tests (Minecraft 26.3)."""
import argparse
import contextlib
import io
import itertools
import json
import random
from pathlib import Path

from generate_schem import resolve_redstone_wires
from repeater_postprocessor import build_graph
from router import route


CASES = [
    ('straight', [[(0,0,True), (0,0,False)]], {}),
    ('uphill', [[(0,0,True), (4,6,False)]], {}),
    ('bottom_source_downhill', [[(0,9,False), (6,0,True)]], {}),
    ('top_to_top', [[(0,0,True), (8,5,True)]], {}),
    ('bottom_to_bottom', [[(0,7,False), (8,1,False)]], {}),
    ('mixed_height_fanout', [[(0,0,True), (4,3,True), (0,6,False), (8,0,False)]], {}),
    ('crossing', [[(0,0,True), (4,0,False)], [(4,0,True), (0,0,False)]], {}),
    ('stacked_straight_two_levels', [[(0,0,True),(0,0,False)], [(0,2,True),(0,2,False)]],
                                  {'width':1,'height':3,'length':11}),
    ('perpendicular_two_levels', [[(4,0,True),(4,0,False)], [(0,2,True),(8,2,True)]],
                                {'width':9,'height':3,'length':7}),
    ('repeater_crossing_two_levels', [[(20,0,True),(20,0,False)], [(0,2,True),(40,2,True)]],
                                   {'width':41,'height':3,'length':11}),
    ('crossing_rising_wire', [[(4,0,True),(4,4,False)], [(0,2,True),(8,2,True)]],
                             {'width':9,'height':5,'length':11}),
    ('crossing_falling_wire', [[(4,4,True),(4,0,False)], [(0,2,True),(8,2,True)]],
                              {'width':9,'height':5,'length':11}),
    ('two_sloped_crossings', [[(0,0,True),(8,4,False)], [(8,0,True),(0,4,False)]],
                             {'width':9,'height':7,'length':13}),
    ('stacked_pins', [[(0,0,True), (4,6,False)], [(0,3,True), (4,0,False)]], {}),
    ('parallel_heights', [[(0,0,True), (0,5,False)], [(4,4,True), (4,0,False)],
                          [(8,2,False), (8,8,True)]], {}),
    ('long_horizontal', [[(0,0,True), (48,0,False)]], {}),
    ('tall_uphill', [[(0,0,True), (0,24,False)]], {}),
    ('tall_downhill', [[(0,24,False), (0,0,True)]], {}),
    ('long_fanout', [[(0,0,True), (20,5,False), (40,0,False), (48,10,True)]], {}),
    ('tall_multilevel_fanout', [[(0,0,True), (4,24,False), (12,12,True), (20,3,False)]], {}),
    ('three_way_cycle', [[(0,0,True), (4,3,False)], [(4,0,True), (8,0,False)],
                         [(8,6,True), (0,0,False)]], {}),
    ('interlocking_fanout', [[(0,0,True), (6,0,False), (12,3,True), (18,0,False)],
                             [(6,0,True), (0,3,False), (18,0,True), (12,0,False)]], {}),
    ('obstacle_wall', [[(0,0,True), (10,6,False)]],
                     {'width': 11, 'length': 15, 'obstacles':
                      {(5,y,z): 'minecraft:stone' for y in range(4) for z in range(1,14)}}),
    ('dense_permutation', [[(i*4,i%3,True), ((4-i)*4,(i*2)%7,False)] for i in range(5)], {}),
    ('fifteen_net_stress', [
        [(0,0,True),(0,0,False)], [(4,2,True),(2,0,False)],
        [(6,0,True),(12,4,False)], [(10,0,True),(8,0,True)],
        [(22,0,True),(20,0,False)], [(20,0,True),(22,0,False)],
        [(14,0,True),(16,0,True),(14,6,False)],
        [(24,0,False),(26,0,False),(24,0,True)],
        [(30,0,True),(28,0,False)], [(28,0,True),(32,0,False)],
        [(32,0,True),(30,0,False)],
        [(34,0,True),(36,0,False),(38,0,True),(40,0,False)],
        [(36,0,True),(34,0,False),(40,0,True),(38,0,False)],
        [(2,0,True),(42,0,False)], [(18,0,True),(18,0,False)]
    ], {}),
]


def postprocess(circuit):
    """Use the production repeater postprocessor, never place them in routing."""
    sources = [(pins[0], 15, 'south') for pins in circuit.net_pins if pins]
    with contextlib.redirect_stdout(io.StringIO()):
        graph, repeaters = build_graph(resolve_redstone_wires(circuit.blocks), sources)
    blocks = circuit.blocks.copy()
    blocks.update({p: f'minecraft:repeater[facing={direction}]' for p, direction in repeaters.items()})
    return blocks, graph, repeaters


def generate(destination, origin=(-480, -60, 240)):
    fixtures = []
    for name, nets, options in CASES:
        circuit = route(nets, **options)
        blocks, graph, repeaters = postprocess(circuit)
        fixture = dict(name=name, circuit=circuit, blocks=blocks, repeaters=repeaters)
        fixtures.append(fixture)
        print(name, (circuit.size_x, circuit.size_y, circuit.size_z), circuit.route_stats,
              f'postprocessor repeaters={len(repeaters)}', flush=True)

    root = destination / 'router_test'
    functions = root / 'data/router_test/function'
    functions.mkdir(parents=True, exist_ok=True)
    (root / 'pack.mcmeta').write_text(json.dumps({'pack': {
        'description': '3D router live electrical regression tests',
        'min_format': [121, 0], 'max_format': [121, 0]}}) + '\n')
    def write(name, commands):
        (functions / f'{name}.mcfunction').write_text('\n'.join(commands) + '\n')
    def pos(p):
        return ' '.join(str(a+b) for a,b in zip(origin, p))
    width = max(f['circuit'].size_x for f in fixtures)
    height = max(f['circuit'].size_y for f in fixtures)
    length = max(f['circuit'].size_z for f in fixtures)
    steps = []
    manifests = []
    rng = random.Random(2026)
    for index, fixture in enumerate(fixtures):
        circuit = fixture['circuit']
        blocks = fixture['blocks'].copy()
        drivers, lamps = [], []
        for pins in circuit.net_pins:
            source = pins[0]
            side = -1 if source[2] == 0 else 1
            driver = (source[0], source[1], source[2]+side)
            facing = 'north' if side == -1 else 'south'
            blocks[driver] = f'minecraft:repeater[facing={facing}]'
            blocks[(driver[0], driver[1]-1, driver[2])] = 'minecraft:white_wool'
            drivers.append((source[0], source[1], source[2]+2*side))
            sinks = []
            for p in pins[1:]:
                outside = -1 if p[2] == 0 else 1
                lamp = (p[0],p[1],p[2]+outside)
                if lamp in blocks:
                    raise ValueError(f'Test driver/lamp collision: {fixture["name"]} {lamp}')
                blocks[lamp] = 'minecraft:redstone_lamp'
                sinks.append(lamp)
            lamps.append(sinks)
        # /fill caps its volume; clearing the whole tall suite at once would
        # silently leave earlier fixtures behind. Split into bounded slabs.
        slab = max(1, 32768 // ((width+2)*(length+4)))
        setup = [f'fill {pos((-1,y,-2))} {pos((width,min(y+slab-1,height+1),length+1))} air'
                 for y in range(0,height+2,slab)]
        setup.append(f'fill {pos((-1,-1,-2))} {pos((width,-1,length+1))} stone_bricks')
        # Supports/lamps precede components; dust last, with far end first.
        order = sorted(blocks.items(), key=lambda item:
                       (2 if 'wire' in item[1] else 1 if 'repeater' in item[1] else 0,
                        -item[0][1], -item[0][2], item[0][0]))
        setup += [f'setblock {pos(p)} {block}' for p,block in order]
        write(f'place_{index}', setup)
        count = len(circuit.net_pins)
        patterns = list(itertools.product((0,1), repeat=count)) if count <= 5 else [
            (0,)*count, (1,)*count, *[tuple(int(i==j) for i in range(count)) for j in range(count)],
            *[tuple(rng.randrange(2) for _ in range(count)) for _ in range(16)]]
        # Exercise rising AND falling edges, including all-off after each drive.
        for pattern in patterns:
            steps.append((index, fixture, pattern, drivers, lamps))
            if any(pattern):
                steps.append((index, fixture, (0,)*count, drivers, lamps))
        manifests.append({'name': fixture['name'], 'dimensions': [circuit.size_x,circuit.size_y,circuit.size_z],
                          'stats': circuit.route_stats, 'repeaters': len(fixture['repeaters']),
                          'nets': circuit.net_pins})
    write('start', [f'schedule clear router_test:check_{i}' for i in range(len(steps))] + [
        f'forceload add {origin[0]-1} {origin[2]-2} {origin[0]+width} {origin[2]+length+1}',
        'scoreboard objectives add router_test dummy',
        'scoreboard players set #passed router_test 0',
        'scoreboard players set #failed router_test 0',
        'data modify storage router_test:results failures set value []',
        'data modify storage router_test:results entries set value []',
        'data modify storage router_test:results status set value "running"',
        'function router_test:apply_0'])
    previous_fixture = None
    for i, (index, fixture, pattern, drivers, lamps) in enumerate(steps):
        commands = []
        if index != previous_fixture:
            commands.append(f'function router_test:place_{index}')
            previous_fixture = index
        commands += [f'setblock {pos(p)} ' + ('redstone_block' if value else 'air')
                     for p,value in zip(drivers,pattern)]
        commands.append(f'schedule function router_test:check_{i} 100t replace')
        write(f'apply_{i}', commands)
        entry = dict(name=fixture['name'], inputs=list(pattern), passed=-1)
        checks = ['scoreboard players set #ok router_test 1',
                  f'data modify storage router_test:results entries append value {json.dumps(entry)}']
        for owner,value in enumerate(pattern):
            lit = 'true' if value else 'false'
            checks += [f'execute unless block {pos(p)} redstone_lamp[lit={lit}] run scoreboard players set #ok router_test 0'
                       for p in lamps[owner]]
            # Check every routed component as well as every sink. This catches
            # crosstalk, missing supports, decay, and stray powered branches.
            for p in fixture['circuit'].net_wires[owner]:
                block = fixture['blocks'][p]
                if 'repeater' in block:
                    checks.append(f'execute unless block {pos(p)} repeater[powered={lit}] run scoreboard players set #ok router_test 0')
                else:
                    comparison = 'if' if value else 'unless'
                    checks.append(f'execute {comparison} block {pos(p)} redstone_wire[power=0] run scoreboard players set #ok router_test 0')
                    checks.append(f'execute unless block {pos(p)} redstone_wire run scoreboard players set #ok router_test 0')
        checks += ['execute store result storage router_test:results entries[-1].passed int 1 run scoreboard players get #ok router_test',
                   'execute if score #ok router_test matches 1 run scoreboard players add #passed router_test 1',
                   'execute if score #ok router_test matches 0 run scoreboard players add #failed router_test 1',
                   'execute if score #ok router_test matches 0 run data modify storage router_test:results failures append from storage router_test:results entries[-1]',
                   f'function router_test:apply_{i+1}' if i+1 < len(steps) else 'function router_test:finish']
        write(f'check_{i}', checks)
    write('finish', ['data modify storage router_test:results status set value "complete"',
                    'execute store result storage router_test:results passed int 1 run scoreboard players get #passed router_test',
                    'execute store result storage router_test:results failed int 1 run scoreboard players get #failed router_test'])
    (root / 'manifest.json').write_text(json.dumps({'origin': origin, 'fixtures': manifests,
                                                 'steps': len(steps), 'ticks': 100*len(steps)}, indent=2) + '\n')
    print(json.dumps({'pack': str(root), 'origin': origin, 'steps': len(steps),
                      'sprint': f'tick sprint {100*len(steps)+200}t'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('datapacks', type=Path)
    parser.add_argument('--origin', nargs=3, type=int, default=(-480,-60,240))
    args = parser.parse_args()
    generate(args.datapacks, tuple(args.origin))
