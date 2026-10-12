"""Height-aware, electrically isolated redstone dust channel router.

Pins are (x, y, is_top); top is z=0, bottom is z=length-1. The first
pin drives the remaining pins, including pins on the same edge. Coordinates
are local, nonnegative integers. Supports may extend to y=-1.
"""
import heapq
import itertools
import random
from collections import deque
from dataclasses import dataclass

from logic_gates import Circuit
from redstone_geometry import HORIZONTAL, signal_neighbors


COLORS = ('white', 'orange', 'magenta', 'light_blue', 'yellow', 'lime',
          'pink', 'gray', 'light_gray', 'cyan', 'purple', 'blue', 'brown',
          'green', 'red', 'black')
GEOMETRIC_PROBE_STATES = 128
AIR_BLOCKS = {'minecraft:air','minecraft:cave_air','minecraft:void_air','air','cave_air','void_air'}


class RoutingError(ValueError):
    """No electrically valid route was found within the supplied limits."""


class _BranchFailure(RoutingError):
    pass


@dataclass(frozen=True)
class Pin:
    x: int
    y: int
    is_top: bool

    def position(self, length):
        return self.x, self.y, 0 if self.is_top else length - 1


def _support(p):
    return p[0], p[1] - 1, p[2]


def _above(p):
    return p[0], p[1] + 1, p[2]


@dataclass(frozen=True, slots=True)
class _Path:
    """Parent-linked path with compact local wire/required-air bitsets."""
    pos: tuple
    parent: object
    wires: int
    clear: int


def _path_blocks(path):
    blocks = []
    while path is not None:
        blocks.append((path.pos, None))
        path = path.parent
    blocks.reverse()
    return tuple(blocks)


class _Layout:
    def __init__(self, width, height, length, nets, obstacles, escape_depth=2, pin_headroom=()):
        self.width, self.height, self.length = width, height, length
        self.pins = {p.position(length): i for i, net in enumerate(nets) for p in net}
        self.exits = {p: (p[0], p[1], 1 if p[2] == 0 else length-2) for p in self.pins}
        self.terminals = dict(self.pins)
        for p, exit_pos in self.exits.items():
            if exit_pos in self.terminals and self.terminals[exit_pos] != self.pins[p]:
                raise RoutingError(f'Pin exit collision at {exit_pos}')
            self.terminals[exit_pos] = self.pins[p]
        self.escape = {}
        for p, owner in self.pins.items():
            z = 2 if p[2] == 0 else length-3
            if 0 < z < length-1:
                for y in (p[1], p[1]+1):
                    guard = (p[0],y,z)
                    if guard in self.escape and self.escape[guard] != owner:
                        raise RoutingError(f'Pin escape collision at {guard}')
                    self.escape[guard] = owner
            # Dense pin banks need an escape all the way to a crossing level;
            # reserving only the first step lets earlier nets roof over it.
            if escape_depth > 2:
                for step in range(3,escape_depth+1):
                    z = step if p[2] == 0 else length-1-step
                    guard = (p[0],p[1]+step-1,z)
                    if 0 < z < length-1:
                        if guard in self.escape and self.escape[guard] != owner:
                            raise RoutingError(f'Pin ramp collision at {guard}')
                        self.escape[guard] = owner
        self.owners = dict(self.terminals)
        self.signals = dict.fromkeys(self.terminals)
        self.supports = {_support(p): owner for p, owner in self.terminals.items()}
        # Only slopes need clear headroom. A flat wire may have the solid
        # support of another wire directly above it (two-level crossing).
        self.clear = {_above(p.position(length)) for p in pin_headroom}
        self.obstacles = dict(obstacles)
        self.layer_stride = width * length
        self._neighbors = {}
        self._bits = {}
        self._static_cache = {}
        self._cache_owner = None
        self.near_nets = {}
        self.near_wires = {}
        for p,owner in self.owners.items():
            self._register_near(p,owner,self.near_nets)
            self._register_near(p,owner,self.near_wires)
        for p,owner in self.escape.items():
            # An optional climb that already shorts a fixed foreign pin exit
            # is impossible, so reserving it would needlessly block a stacked
            # flat line. Fixed terminal geometry still provides isolation.
            if not (self.near_wires.get(p,0) & ~(1 << owner)):
                self._register_near(p,owner,self.near_nets)
        if self.clear.intersection(self.supports) or self.clear.intersection(self.signals) or self.clear.intersection(obstacles):
            raise RoutingError('A pin interface requires headroom occupied by a block/support')
        for pos in self.terminals:
            if pos in obstacles or _support(pos) in self.signals:
                raise RoutingError(f'Pin/support collision at {pos}')
            if _support(pos) in obstacles and not _is_solid(obstacles[_support(pos)]):
                raise RoutingError(f'Pin support obstructed at {pos}')
            for dx, dz in HORIZONTAL + ((0, 0),):
                for dy in (-1, 0, 1):
                    other = (pos[0]+dx, pos[1]+dy, pos[2]+dz)
                    if other in self.owners and self.owners[other] != self.owners[pos]:
                        raise RoutingError(f'Pin exits would short at {pos} and {other}')
        self._reserve_slopes(self.terminals)

    def bit(self, p):
        # Extra bottom plane represents supports at y=-1. Shifting wire bits
        # down a plane gives all local supports without allocating another set.
        bit = self._bits.get(p)
        if bit is None:
            bit = 1 << ((p[1]+1)*self.layer_stride + p[2]*self.width + p[0])
            self._bits[p] = bit
        return bit

    def neighbors(self, p):
        adjacent = self._neighbors.get(p)
        if adjacent is None:
            x,y,z = p
            adjacent = tuple((x+dx,y+dy,z+dz) for dx,dz in HORIZONTAL for dy in (-1,0,1)
                             if 0 <= x+dx < self.width and 0 <= y+dy < self.height
                             and 0 <= z+dz < self.length)
            self._neighbors[p] = adjacent
        return adjacent

    def _register_near(self, p, owner, mask):
        owner_bit = 1 << owner
        x,y,z = p
        for dx,dz in HORIZONTAL + ((0,0),):
            for dy in (-1,0,1):
                q = (x+dx,y+dy,z+dz)
                if 0 <= q[0] < self.width and 0 <= q[1] < self.height and 0 <= q[2] < self.length:
                    mask[q] = mask.get(q,0) | owner_bit

    def adjacent_bits(self, p):
        x,y,z = p
        bit = self.bit(p)
        horizontal = 0
        if x > 0:
            horizontal |= bit >> 1
        if x+1 < self.width:
            horizontal |= bit << 1
        if z > 0:
            horizontal |= bit >> self.width
        if z+1 < self.length:
            horizontal |= bit << self.width
        return horizontal | (horizontal << self.layer_stride) | (horizontal >> self.layer_stride)

    def _static_valid(self, pos, owner):
        if self._cache_owner != owner:
            self._cache_owner = owner
            self._static_cache.clear()
        if pos in self._static_cache:
            return self._static_cache[pos]
        result = self._check_static(pos, owner)
        self._static_cache[pos] = result
        return result

    def _check_static(self, pos, owner):
        x,y,z = pos
        if not (0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.length):
            return False
        if z in (0,self.length-1) and self.pins.get(pos) != owner:
            return False
        if pos in self.obstacles or pos in self.supports or pos in self.clear:
            return False
        if pos in self.signals and self.terminals.get(pos) != owner:
            return False
        support = _support(pos)
        if support in self.signals or support in self.clear:
            return False
        if support in self.obstacles and not _is_solid(self.obstacles[support]):
            return False
        # Same-level and one-level diagonal adjacency can connect different
        # nets. Two-level stacking is allowed; slopes protect their throats.
        return not (self.near_nets.get(pos,0) & ~(1 << owner))

    def valid(self, pos, owner, local):
        if not self._static_valid(pos,owner):
            return False
        wires, clear = local
        wire = self.bit(pos)
        support = wire >> self.layer_stride
        return not (wire & (wires | clear | (wires >> self.layer_stride)) or
                    support & (wires | clear))

    def step_clear(self, current, end, local):
        if current[1] == end[1]:
            return 0
        throat = _above(current if current[1] < end[1] else end)
        if throat in self.supports or throat in self.obstacles or throat in self.signals:
            return None
        bit = self.bit(throat)
        if bit & (local[0] | (local[0] >> self.layer_stride)):
            return None
        return bit

    def _reserve_slopes(self, positions):
        for p in positions:
            for other in self.neighbors(p):
                if p[1] != other[1] and self.owners.get(other) == self.owners[p]:
                    throat = _above(p if p[1] < other[1] else other)
                    if throat not in self.supports and throat not in self.obstacles:
                        self.clear.add(throat)

    def commit(self, additions, owner):
        for pos, direction in additions:
            if pos not in self.signals:
                self._register_near(pos,owner,self.near_nets)
                self._register_near(pos,owner,self.near_wires)
            self.signals[pos] = direction
            self.owners[pos] = owner
            self.supports[_support(pos)] = owner
        self._reserve_slopes(p for p,d in additions)
        self._static_cache.clear()

    def release_escape(self, owner):
        """Once a net is complete, its real geometry replaces optional ramps."""
        self.escape = {p:n for p,n in self.escape.items() if n != owner}
        self.near_nets = dict(self.near_wires)
        for p,n in self.escape.items():
            if not (self.near_wires.get(p,0) & ~(1 << n)):
                self._register_near(p,n,self.near_nets)
        self._static_cache.clear()


def _is_solid(block):
    return not any(name in block for name in (
        'air', 'wire', 'repeater', 'torch', 'lever', 'sign', 'water', 'lava',
        'glass', 'slab', 'stairs', 'leaves', 'fence', 'wall', 'carpet',
        'rail', 'snow', 'trapdoor', 'bars'))


def _distance(pos, target):
    # A staircase changes height AND a horizontal coordinate at once.
    dy = abs(pos[1] - target[1])
    return max(abs(pos[0] - target[0]) + abs(pos[2] - target[2]), dy) + .35*dy


def _routing_potential(layout, owner, tree, target):
    """Reverse flood through static legal geometry, for congested channels."""
    empty = (0,0)
    if target not in tree and not layout.valid(target,owner,empty):
        return {}
    distances, queue = {target:0}, deque([target])
    while queue:
        current = queue.popleft()
        x,y,z = current
        for p in layout.neighbors(current):
            if p in distances or (p not in tree and not layout.valid(p,owner,empty)):
                continue
            if z in (0,layout.length-1) or p[2] in (0,layout.length-1):
                if p[0] != x or p[1] != y:
                    continue
            if layout.step_clear(current,p,empty) is None:
                continue
            distances[p] = distances[current] + 1
            queue.append(p)
    return distances


def _branch_seeds(layout, owner, tree):
    """Distance since an upstream flat landing, excluding the new junction.

    Branching removes a straight site's eligibility. Count from an earlier
    site instead, and preserve the other sites by keeping new branches trees.
    This is geometry planning only; repeater placement remains downstream.
    """
    signals = {p:None for p in layout.signals if layout.owners[p] == owner}
    solids = set(layout.supports) | set(layout.obstacles)
    neighbors = {p:list(signal_neighbors(p,signals,solids)) for p in tree}
    eligible = set()
    for p, adjacent in neighbors.items():
        if len(adjacent) == 2:
            a,b = adjacent
            if a[1] == p[1] == b[1] and (a[0]+b[0],a[2]+b[2]) == (2*p[0],2*p[2]):
                eligible.add(p)
    source = next(iter(tree))
    gaps, seeds, queue = {source:0}, {source:0}, deque([source])
    while queue:
        pos = queue.popleft()
        for child in neighbors[pos]:
            if child in tree and child not in gaps:
                before = gaps[pos] + 1
                gaps[child] = 0 if child in eligible else before
                if before <= 10:
                    seeds[child] = before
                queue.append(child)
    return seeds


def _touches_only_path(layout, owner, local, current, end, target):
    """Prevent accidental same-net loops/extra branches from removing landings."""
    unexpected = local[0] & layout.adjacent_bits(end) & ~layout.bit(current)
    if not unexpected and not (layout.near_wires.get(end,0) & (1 << owner)):
        return True
    for p in layout.neighbors(end):
        if layout.owners.get(p) == owner or layout.bit(p) & local[0]:
            if p not in (current,target) and layout.exits.get(p) != target:
                if layout.step_clear(end,p,local) is not None:
                    return False
    return True


def _find_branch(layout, owner, tree, target, max_states, informed=False):
    seeds = _branch_seeds(layout,owner,tree)
    # Fast path for long straight-column stairs. Weighted search otherwise
    # spends its budget considering many equivalent landing locations.
    for start in sorted(seeds, key=lambda p: (_distance(p,target), p)):
        vertical = abs(start[1]-target[1])
        run = abs(start[2]-target[2])
        if (start[0] != target[0] or run < vertical + 2*max(0,(vertical-1)//9)
                or start[2] in (0,layout.length-1)):
            continue
        dz = 1 if target[2] > start[2] else -1
        dy = 1 if target[1] > start[1] else -1
        pos, path, stairs, flats = start, None, seeds[start], 0
        local = (0,0)
        for _ in range(run):
            climb = pos[1] != target[1] and stairs < 9
            end = (pos[0],pos[1] + (dy if climb else 0),pos[2]+dz)
            if (end in tree or not layout.valid(end,owner,local) or
                    not _touches_only_path(layout,owner,local,pos,end,target)):
                break
            throat = layout.step_clear(pos,end,local)
            if throat is None:
                break
            local = (local[0] | layout.bit(end), local[1] | throat)
            path = _Path(end,path,*local)
            pos = end
            if climb:
                stairs += 1
                flats = 0
            else:
                flats += 1
                if flats >= 2:
                    stairs = 0
        else:
            if pos == target:
                return _path_blocks(path)
    potential = _routing_potential(layout,owner,tree,target) if informed else None
    def estimate(pos):
        if potential is None:
            return _distance(pos,target)
        return potential.get(pos,float('inf')) + .35*abs(pos[1]-target[1])
    counter = itertools.count()
    queue, best = [], {}
    for pos,gap in seeds.items():
        if potential is None or pos in potential:
            best[(pos,None,gap)] = 0.
            heapq.heappush(queue, (1.5*estimate(pos), 0., next(counter), pos, None, gap, None))
    expanded = 0
    # Easy branches finish using a cheap geometric heuristic. Congested ones
    # switch early to an obstacle-aware field instead of spending the entire
    # budget rediscovering a blocked pin bank before trying reverse search.
    probe_limit = max_states if informed else min(max_states,GEOMETRIC_PROBE_STATES)
    while queue and expanded < probe_limit:
        _, cost, _, pos, previous, gap, path = heapq.heappop(queue)
        if pos == target:
            return _path_blocks(path)
        state = (pos, previous, gap)
        if cost != best[state]:
            continue
        expanded += 1
        local = (path.wires,path.clear) if path is not None else (0,0)
        x, y, z = pos
        for dx, dz in HORIZONTAL:
            # Boundary pins enter/leave the channel straight at their own height.
            if z == 0 and (dx, dz) != (0, 1):
                continue
            if z == layout.length - 1 and (dx, dz) != (0, -1):
                continue
            for dy in (0, 1, -1):
                if z in (0, layout.length - 1) and dy:
                    continue
                end = (x + dx, y + dy, z + dz)
                if end in tree:
                    continue
                if potential is not None and end not in potential:
                    continue
                if end[2] in (0, layout.length - 1) and (dx != 0 or dy != 0):
                    continue
                if not layout.valid(end, owner, local):
                    continue
                throat = layout.step_clear(pos,end,local)
                if throat is None or not _touches_only_path(layout,owner,local,pos,end,target):
                    continue
                direction = (dx, dy, dz)
                # Keep legal flat repeater sites within reach on long climbs
                # and winding routes. Placement belongs to the postprocessor.
                landing = dy == 0 and previous == direction
                next_gap = 0 if landing else gap + 1
                if next_gap > 11:
                    continue
                step_cost = 1 + .35 * abs(dy) + (.2 if previous and previous != direction else 0)
                new_cost = cost + step_cost
                new_state = (end,direction,next_gap)
                if new_cost >= best.get(new_state,float('inf')):
                    continue
                best[new_state] = new_cost
                next_path = _Path(end,path,local[0] | layout.bit(end),local[1] | throat)
                heapq.heappush(queue, (new_cost + 1.5*estimate(end), new_cost,
                                      next(counter), end, direction, next_gap, next_path))
    if not informed:
        return _find_branch(layout,owner,tree,target,max_states,informed=True)
    return None


def _attempt(nets, width, height, length, order, obstacles, max_states, escape_depth=2, pin_headroom=()):
    layout = _Layout(width, height, length, nets, obstacles, escape_depth, pin_headroom)
    for owner in order:
        coordinates = [p.position(length) for p in nets[owner]]
        if not coordinates:
            continue
        source = coordinates[0]
        tree = {source: None, layout.exits[source]: None}
        remaining = {layout.exits[p] for p in coordinates[1:]}
        while remaining:
            remaining.difference_update(tree)
            if not remaining:
                break
            target = min(remaining, key=lambda t: (min(_distance(p, t) for p in tree), t))
            path = _find_branch(layout, owner, tree, target, max_states)
            if path is None:
                raise _BranchFailure(f'Net {owner+1}: no branch from {source} to {target}')
            layout.commit(path, owner)
            tree.update(path)
        layout.release_escape(owner)
    return layout


def route(nets_input, top_gates=None, bot_gates=None, warn_overwrite=False, *,
          width=None, height=None, length=None, max_height=None, max_length=None,
          obstacles=None, attempts=6, max_states=20000, min_width=1, pin_headroom=()):
    """Route source-first nets, growing compact channels unless bounds are fixed.

    `width`, `height`, `length` fix respective bounds; otherwise the router
    tries increasing footprint/height budgets. `max_height`/`max_length` bound
    automatic growth. `obstacles` maps local coordinates to existing blocks.
    Supports must be full solid blocks; existing geometry is never overwritten.
    Only dust and supports are generated; run the repeater postprocessor next.
    The result exposes `net_wires`, `net_pins`, `routing_repeaters`, `route_stats`.
    """
    nets, used = [], {}
    for owner, net in enumerate(nets_input):
        pins = []
        for raw in net:
            if len(raw) != 3:
                raise ValueError(f'Invalid pin: {raw!r}; expected (x, y, is_top)')
            x, y, side = raw
            if type(x) is not int or type(y) is not int or x < 0 or y < 0 or type(side) is not bool:
                raise ValueError(f'Invalid pin: {raw!r}; x/y must be nonnegative integers and side a bool')
            pin = Pin(x, y, side)
            if pin in used and used[pin] != owner:
                raise ValueError(f'Pin {raw} is used by multiple nets')
            used[pin] = owner
            if pin not in pins:
                pins.append(pin)
        nets.append(pins)
    if attempts < 1 or max_states < 1:
        raise ValueError('attempts and max_states must be positive')
    for name, bound in (('width', width), ('height', height), ('length', length),
                        ('max_height', max_height), ('max_length', max_length), ('min_width', min_width)):
        if bound is not None and (type(bound) is not int or bound < (3 if 'length' in name else 1)):
            raise ValueError(f'{name} must be a positive integer (length at least 3)')
    obstacles = {p:b for p,b in (obstacles or {}).items() if b.split('[',1)[0] not in AIR_BLOCKS}
    for pos in obstacles:
        if (len(pos) != 3 or any(type(v) is not int for v in pos) or
                pos[0] < 0 or pos[1] < -1 or pos[2] < 0):
            raise ValueError(f'Invalid obstacle coordinate: {pos!r}')
    pins = list(used)
    pin_headroom = {Pin(*p) for p in pin_headroom}
    if not pin_headroom.issubset(used):
        raise ValueError('pin_headroom must refer to actual routing pins')
    min_width = max([p.x + 1 for p in pins] + [min_width] + [p[0]+1 for p in obstacles] +
                    [getattr(g, 'x_offset', 0) + g.size_x for g in list(top_gates or []) + list(bot_gates or [])])
    min_height = max([p.y + 1 for p in pins] + [1] + [p[1]+1 for p in obstacles])
    max_height = max_height if max_height is not None else max(height or 0, min_height + max(6, len(nets)))
    max_length = max_length if max_length is not None else max(length or 0, 15, min_height * 2 + 5, len(nets) * 4 + 5)
    widths = [width] if width is not None else [min_width, min_width + 2, min_width + 4]
    heights = [height] if height is not None else sorted({min_height, min_height + 2, max_height})
    height_delta = max((max(p.y for p in net) - min(p.y for p in net)
                        for net in nets if net), default=0)
    # Tall endpoints need staircase run and flat landings. Start with that
    # physical estimate instead of repeatedly exhausting tiny flat channels.
    start_length = max(3, height_delta + 3 + 2*(height_delta // 8) - (min_width - 1))
    start_length = max(start_length, max((p[2]+1 for p in obstacles), default=3))
    lengths = [length] if length is not None else list(range(start_length, max_length + 1, 2))
    candidates = [(w, h, l) for w in widths for h in heights for l in lengths
                  if w >= min_width and h >= min_height and h <= max_height and l >= 3 and l <= max_length]
    candidates.sort(key=lambda b: (b[0]*b[2] + .5*b[0]*max(0, b[1]-min_height), b[1], b[2], b[0]))
    rng = random.Random(42)
    count = 0
    last_error = None
    for w, h, l in candidates:
        spans = {i: max((_distance(net[0].position(l), p.position(l)) for p in net), default=0)
                 for i, net in enumerate(nets)}
        orders = [sorted(range(len(nets)), key=lambda i: (spans[i], -len(nets[i]), i))]
        reverse_order = sorted(range(len(nets)), key=lambda i: (-len(nets[i]), -spans[i], i))
        if reverse_order not in orders:
            orders.append(reverse_order)
        for _ in range(max(0, attempts - 2)):
            order = list(range(len(nets)))
            rng.shuffle(order)
            if order not in orders:
                orders.append(order)
        for order in orders[:attempts]:
            count += 1
            try:
                budget = min(max_states, max(1000, w*h*l*3))
                layout = _attempt(nets, w, h, l, order, obstacles, budget, pin_headroom=pin_headroom)
            except _BranchFailure as error:
                # Keep diagnostics, not exception tracebacks retaining entire
                # failed layouts, caches and search paths between retries.
                last_error = str(error)
                if h < 3 or l < 7:
                    continue
                # Retry the same compact box with deeper pin escape cones
                # before increasing dimensions. Only difficult layouts need
                # these reservations; easy ones keep their shorter channels.
                count += 1
                try:
                    layout = _attempt(nets,w,h,l,order,obstacles,budget,escape_depth=3,pin_headroom=pin_headroom)
                except RoutingError as error:
                    last_error = str(error)
                    continue
            except RoutingError as error:
                last_error = str(error)
                break
            if layout is None:
                continue
            circuit = Circuit(w, max([p[1] + 1 for p in layout.signals] +
                                     [p[1]+1 for p in obstacles] + [1]), l)
            circuit.blocks.update(obstacles)
            for pos, owner in layout.supports.items():
                if pos not in circuit.blocks:
                    circuit.set_block(*pos, f'minecraft:{COLORS[owner % len(COLORS)]}_wool')
            for pos in layout.signals:
                circuit.set_block(*pos, 'minecraft:redstone_wire')
            circuit.net_wires = [{p: d for p, d in layout.signals.items() if layout.owners[p] == i}
                                 for i in range(len(nets))]
            circuit.net_pins = [[p.position(l) for p in net] for net in nets]
            circuit.routing_repeaters = set()
            circuit.required_air = set(layout.clear)
            circuit.route_stats = {'attempts': count, 'wire_blocks': len(layout.signals),
                                   'repeaters': 0, 'footprint': w*l,
                                   'height': circuit.size_y}
            return circuit
    detail = f'; {last_error}' if last_error else ''
    raise RoutingError(f'No route found after {count} attempts (max height {max_height}, '
                       f'max length {max_length}){detail}')


def apply_lowering(circuit):
    """Compatibility hook: routing already minimizes height-change costs."""
    return None
