"""Hand-built electrical adversaries, independent of router search heuristics."""
from dataclasses import dataclass

from generate_schem import resolve_redstone_wires


@dataclass
class Fixture:
    name: str
    blocks: dict
    sources: list
    nets: list
    expected_error: bool = False


def fixture(name, paths, roots, existing=None, obstacles=None, expected_error=False):
    """Paths belonging to one net may meet; separate nets must not touch."""
    blocks = dict(obstacles or {})
    nets = []
    for paths_for_net in paths:
        wires = set()
        for path in paths_for_net:
            wires.update(path)
        nets.append(sorted(wires))
        for x,y,z in wires:
            blocks[x,y-1,z] = 'minecraft:white_wool'
        for p in wires:
            blocks[p] = 'minecraft:redstone_wire'
    for p,facing in (existing or {}).items():
        blocks[p] = f'minecraft:repeater[facing={facing}]'
    return Fixture(name,resolve_redstone_wires(blocks),
                   [(p,15,'south') for p in roots],nets,expected_error)


def stress_fixtures():
    cases = []
    # Includes exact decay boundaries and a long line: the first repeater can
    # replace dust that would have power zero if its input still has power one.
    for length in (14,15,16,29,30,31,32,45,46,47,48,62,63,94,95):
        cases.append(fixture(f'line_{length}',[[[(x,1,0) for x in range(length+1)]]],[(0,1,0)]))
    for trunk,arm in ((10,14),(12,13),(13,14),(14,16),(26,14)):
        paths = [[(x,1,0) for x in range(trunk+1)],
                 [(trunk,1,z) for z in range(-arm,arm+1)]]
        cases.append(fixture(f'fork_{trunk}_{arm}',[paths],[(0,1,0)]))
    # Multiple forks reward sharing restoration before branching rather than
    # independently inserting one repeater down each arm.
    paths = [[(x,1,0) for x in range(61)]]
    paths += [[(x,1,z) for z in range(-13,14)] for x in (10,26,42,58)]
    cases.append(fixture('comb_shared_trunk',[paths],[(0,1,0)]))
    # Consecutive corners with only a few usable landings.
    path = [(x,1,0) for x in range(12)]
    path += [(11,1,z) for z in range(1,12)]
    path += [(x,1,11) for x in range(12,32)]
    cases.append(fixture('sparse_corner_landings',[[path]],[(0,1,0)]))
    for reverse in (False,True):
        path = [(x,1,0) for x in range(12)]
        path += [(11+i,1+i,0) for i in range(1,9)]
        path += [(x,9,0) for x in range(20,43)]
        if reverse:
            path.reverse()
        cases.append(fixture('stairs_down' if reverse else 'stairs_up',[[path]],[path[0]]))
    # Y+2 crossing: the upper support covers lower dust but must not cause
    # cross-power, repeater locking, or prevent valid flat restoration.
    cases.append(fixture('stacked_crossing',[
        [[(x,1,0) for x in range(49)]],
        [[(24,3,z) for z in range(-24,25)]]],[(0,1,0),(24,3,-24)]))
    cases.append(fixture('fixed_repeaters',[[[(x,1,0) for x in range(64)]]],
                         [(0,1,0)],existing={(8,1,0):'west',(9,1,0):'west'}))
    path = [(x,x+1,0) for x in range(15)]
    path += [(15,15,0),(16,15,0)]
    path += [(16+i,15+i,0) for i in range(1,7)]
    cases.append(fixture('only_landing_at_zero',[[path]],[path[0]]))
    # Dust cycles with no restoration inside the cycle must turn back OFF.
    # The entry trunk needs restoration; the small ring itself does not.
    paths = [[(x,1,0) for x in range(32)],
             [(31,1,z) for z in range(7)],[(37,1,z) for z in range(7)],
             [(x,1,z) for x in range(31,38) for z in (0,6)]]
    cases.append(fixture('small_loop_long_feed',[paths],[(0,1,0)]))
    for trunk,side in ((9,3),(12,3),(27,3),(3,12),(1,7),(0,17),(15,17)):
        paths = [[(x,1,0) for x in range(trunk+1)],
                 [(trunk,1,z) for z in range(side+1)],
                 [(trunk+side,1,z) for z in range(side+1)],
                 [(x,1,z) for x in range(trunk,trunk+side+1) for z in (0,side)]]
        cases.append(fixture(f'loop_{trunk}_{side}',[paths],[(0,1,0)]))
    for length in (12,40):
        cases.append(fixture(f'two_sources_{length}',[[[(x,1,0) for x in range(length+1)]]],
                             [(0,1,0),(length,1,0)],expected_error=length > 14))
    # No flat site can bridge this long staircase: explicit failure is required.
    path = [(x,x+1,0) for x in range(22)]
    cases.append(fixture('impossible_staircase',[[path]],[path[0]],expected_error=True))
    return cases
