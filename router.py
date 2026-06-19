import heapq
import copy
from logic_gates import Circuit

# Configurable A* Router step costs/penalties
BASE_STEP_COST = 1.0               # Cost of moving along the X axis
Z_STEP_COST = 5.0                  # Cost of moving along the Z axis (channel length direction)
BEND_PENALTY = 2.0
VERTICAL_STEP_PENALTY = 10.0       # Penalty for changing Y-level (climb/descend)
HEIGHT_PENALTY_MULTIPLIER = 3.0   # Multiplier applied to Y level to keep paths on the floor (Y=0)



class Pin:
    def __init__(self, x, y, is_top):
        self.x = int(x)
        self.y = int(y)
        self.is_top = is_top

class Net:
    def __init__(self, net_id, pins):
        self.id = net_id
        self.pins = pins # List of Pin objects
        self.track = -1
        self.dogleg_x = -1
        self.outpath = False
        self.out_partner = None

    def get_x_min(self):
        m = min(p.x for p in self.pins) if self.pins else 0
        if self.dogleg_x != -1: m = min(m, self.dogleg_x)
        return m

    def get_x_max(self):
        m = max(p.x for p in self.pins) if self.pins else 0
        if self.dogleg_x != -1: m = max(m, self.dogleg_x)
        return m

    def overlaps(self, other):
        return not (self.get_x_max() < other.get_x_min() - 1 or self.get_x_min() > other.get_x_max() + 1)

def is_short_with_other_nets(x, y, z, net_id, occupied_wires, occupied_supports, temp_supports):
    # 1. Check cardinal neighbors (must not contain wires of other nets)
    for dx, dy, dz in [(0,0,1), (0,0,-1), (0,1,0), (0,-1,0), (1,0,0), (-1,0,0)]:
        nx, ny, nz = x + dx, y + dy, z + dz
        if (nx, ny, nz) in occupied_wires:
            if occupied_wires[(nx, ny, nz)] != net_id:
                return True
                
    # 2. Check diagonal step connections in the 4 cardinal horizontal directions
    for dx, dz in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        # Climbing diagonal
        npos_up = (x + dx, y + 1, z + dz)
        if npos_up in occupied_wires and occupied_wires[npos_up] != net_id:
            # Throat is at (x, y + 1, z)
            throat = (x, y + 1, z)
            if throat not in occupied_supports and throat not in temp_supports:
                return True
                
        # Descending diagonal
        npos_down = (x + dx, y - 1, z + dz)
        if npos_down in occupied_wires and occupied_wires[npos_down] != net_id:
            # Throat is at (x + dx, y, z + dz)
            throat = (x + dx, y, z + dz)
            if throat not in occupied_supports and throat not in temp_supports:
                return True
                
    return False

def is_pin_exit_of_other_net(nx, ny, nz, net_id, nets, length):
    for n in nets:
        if n.id != net_id:
            for p in n.pins:
                if p.is_top:
                    if nx == p.x and nz == 1:
                        return True
                    if nx == p.x and nz == 2 and ny in [0, 1]:
                        return True
                else:
                    if nx == p.x and nz == length - 2:
                        return True
                    if nx == p.x and nz == length - 3 and ny in [0, 1]:
                        return True
    return False

def is_transition_valid(curr, next_pos, net_id, occupied_wires, occupied_supports, temp_supports, size_x, size_y, size_z, nets):
    cx, cy, cz = curr
    nx, ny, nz = next_pos
    if not (0 <= nx < size_x and 0 <= ny < size_y and 0 <= nz < size_z):
        return False
        
    # Forbid horizontal routing along the Z=0 and Z=size_z-1 edges
    if nz == 0 or nz == size_z - 1:
        is_own_pin = False
        for n in nets:
            if n.id == net_id:
                for p in n.pins:
                    pz = 0 if p.is_top else size_z - 1
                    if nx == p.x and ny == 0 and nz == pz:
                        is_own_pin = True
                        break
        if not is_own_pin:
            return False
        
    # Standard wire and support collision
    if (nx, ny, nz) in occupied_wires and occupied_wires[(nx, ny, nz)] != net_id:
        return False
    if (nx, ny, nz) in occupied_supports and occupied_supports[(nx, ny, nz)] != net_id:
        return False
        
    # Enforce at most one wire per vertical column (nx, nz) for the SAME net
    for y in range(size_y):
        if y != ny:
            if (nx, y, nz) in occupied_wires and occupied_wires[(nx, y, nz)] == net_id:
                return False
                
    # Pin exit reservation check
    if is_pin_exit_of_other_net(nx, ny, nz, net_id, nets, size_z):
        return False
        
    # Spacing and short check
    if is_short_with_other_nets(nx, ny, nz, net_id, occupied_wires, occupied_supports, temp_supports):
        return False
        
    # Support block check
    if ny > 0:
        sy = ny - 1
        if (nx, sy, nz) in occupied_wires and occupied_wires[(nx, sy, nz)] != net_id:
            return False
        if (nx, sy, nz) in occupied_supports and occupied_supports[(nx, sy, nz)] != net_id:
            return False
            
    # Check throat block for vertical transitions
    dy = ny - cy
    if dy == 1:
        throat = (cx, cy + 1, cz)
        if (throat in occupied_wires and occupied_wires[throat] != net_id) or \
           (throat in occupied_supports and occupied_supports[throat] != net_id):
            return False
    elif dy == -1:
        throat = (nx, ny + 1, nz)
        if (throat in occupied_wires and occupied_wires[throat] != net_id) or \
           (throat in occupied_supports and occupied_supports[throat] != net_id):
            return False
            
    return True

def get_heuristic(pos, targets):
    return min(abs(pos[0] - tx) + abs(pos[1] - ty) + abs(pos[2] - tz) for tx, ty, tz in targets)

def find_path(start, targets, net_id, occupied_wires, occupied_supports, size_x, size_y, size_z, nets):
    counter = 0
    pq = []
    h = get_heuristic(start, targets)
    heapq.heappush(pq, (h, 0.0, counter, start, None, [start]))
    
    best_g = {}
    
    moves = [
        # Horizontal cardinal
        (0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0),
        # Climbing vertical diagonal
        (0, 1, 1), (0, 1, -1), (1, 1, 0), (-1, 1, 0),
        # Descending vertical diagonal
        (0, -1, 1), (0, -1, -1), (1, -1, 0), (-1, -1, 0)
    ]
    
    while pq:
        f, g, _, curr, prev, path = heapq.heappop(pq)
        
        if curr in targets:
            return path
            
        prev_dir = None
        if prev is not None:
            prev_dir = (curr[0] - prev[0], curr[1] - prev[1], curr[2] - prev[2])
            
        state_key = (curr, prev_dir)
        if state_key in best_g and best_g[state_key] <= g:
            continue
        best_g[state_key] = g
        
        # Build set of temporary support coordinates for the current path
        temp_supports = set()
        for p in path:
            if p[1] > 0:
                temp_supports.add((p[0], p[1] - 1, p[2]))
        
        for dx, dy, dz in moves:
            npos = (curr[0] + dx, curr[1] + dy, curr[2] + dz)
            
            if is_transition_valid(curr, npos, net_id, occupied_wires, occupied_supports, temp_supports, size_x, size_y, size_z, nets):
                step_cost = BASE_STEP_COST if dx != 0 else Z_STEP_COST
                if prev_dir is not None:
                    next_dir = (npos[0] - curr[0], npos[1] - curr[1], npos[2] - curr[2])
                    if prev_dir != next_dir:
                        step_cost += BEND_PENALTY
                if npos[1] != curr[1]:
                    step_cost += VERTICAL_STEP_PENALTY
                # Encourage paths to run on floor level (Y=0) where possible
                step_cost += npos[1] * HEIGHT_PENALTY_MULTIPLIER
                    
                next_g = g + step_cost
                next_dir = (npos[0] - curr[0], npos[1] - curr[1], npos[2] - curr[2])
                next_state_key = (npos, next_dir)
                
                if next_state_key not in best_g or best_g[next_state_key] > next_g:
                    counter += 1
                    next_f = next_g + get_heuristic(npos, targets)
                    heapq.heappush(pq, (next_f, next_g, counter, npos, curr, path + [npos]))
                    
    return None

def get_net_length_heuristic(net, length):
    coords = []
    for p in net.pins:
        z = 0 if p.is_top else length - 1
        coords.append((p.x, 0, z))
    xs = [c[0] for c in coords]
    zs = [c[2] for c in coords]
    return (max(xs) - min(xs)) + (max(zs) - min(zs))

def route(nets_input, top_gates=None, bot_gates=None, warn_overwrite=False):
    # 0. Validate pins: Ensure no two different nets use the same pin coordinate
    pin_to_net = {}
    for i, pin_list in enumerate(nets_input):
        for (px, py, is_top) in pin_list:
            coord = (px, py, is_top)
            if coord in pin_to_net:
                if pin_to_net[coord] != i:
                    side = "Top" if is_top else "Bottom"
                    raise ValueError(f"EXCEPTION: Pin at {side} X={px} is used by multiple nets (Net {pin_to_net[coord]+1} and Net {i+1})!")
            pin_to_net[coord] = i

    # 1. Initialize Net objects
    nets = []
    for i, pin_list in enumerate(nets_input):
        net_pins = [Pin(px, py, is_top) for (px, py, is_top) in pin_list]
        nets.append(Net(i + 1, net_pins))

    # 2. VCG and doglegs (original track count estimation for length sizing) using a deep copy of nets
    nets_est = copy.deepcopy(nets)
    
    occupied_xs = set()
    for g in (top_gates or []):
        off = getattr(g, 'x_offset', 0)
        for x in range(off, off + g.size_x): occupied_xs.add(x)
    for g in (bot_gates or []):
        off = getattr(g, 'x_offset', 0)
        for x in range(off, off + g.size_x): occupied_xs.add(x)
    for n in nets_est:
        for p in n.pins: occupied_xs.add(p.x)

    x_map = {}
    for n in nets_est:
        for p in n.pins:
            if p.x not in x_map: x_map[p.x] = {'top': set(), 'bot': set()}
            if p.is_top: x_map[p.x]['top'].add(n.id)
            else: x_map[p.x]['bot'].add(n.id)

    adj = {n.id: set() for n in nets_est}
    def has_path(u, v):
        vis = {u}; q = [u]
        while q:
            curr = q.pop(0)
            for neighbor in adj.get(curr, []):
                if neighbor == v: return True
                if neighbor not in vis:
                    vis.add(neighbor)
                    q.append(neighbor)
        return False

    final_nets = list(nets_est)
    for x in sorted(list(x_map.keys())):
        tops, bots = x_map[x]['top'], x_map[x]['bot']
        for t in tops:
            for b in bots:
                if t != b:
                    if has_path(t, b):
                        dog_id = t + 50000
                        t_net = next(n for n in nets_est if n.id == t)
                        best_x = -1
                        cand_dist = 0
                        while best_x == -1:
                            for dx in [cand_dist, -cand_dist]:
                                cand = x + dx
                                if cand >= 0 and cand % 2 == 0 and cand not in occupied_xs:
                                    best_x = cand
                                    break
                            if best_x != -1: break
                            cand_dist += 1
                        occupied_xs.add(best_x)
                        conflict_pins = [p for p in t_net.pins if p.x == x and p.is_top]
                        for cp in conflict_pins: t_net.pins.remove(cp)
                        d_net = Net(dog_id, conflict_pins)
                        d_net.outpath = True
                        d_net.dogleg_x = best_x
                        d_net.out_partner = t_net
                        t_net.out_partner = d_net
                        t_net.dogleg_x = best_x
                        adj[dog_id] = set()
                        if t in adj[b]: adj[b].remove(t)
                        adj[b].add(dog_id)
                        final_nets.append(d_net)
                    else:
                        adj[b].add(t)

    remaining = list(final_nets)
    straight_nets = []
    for n in list(remaining):
        if n.get_x_min() == n.get_x_max() and not n.outpath:
            is_independent = True
            for other_id, deps in adj.items():
                if n.id in deps:
                    is_independent = False; break
            if is_independent and not adj[n.id]:
                straight_nets.append(n)
                remaining.remove(n)
                n.track = -2

    routed = []
    tracks = []
    while remaining:
        ready = [n for n in remaining if all(dep not in [rn.id for rn in remaining] for dep in adj.get(n.id, []))]
        ready.sort(key=lambda n: n.get_x_min())
        if not ready: break
        for n in ready:
            min_t = 0
            for dep in adj.get(n.id, []):
                try:
                    dep_net = next(rn for rn in routed if rn.id == dep)
                    min_t = max(min_t, dep_net.track + 1)
                except StopIteration:
                    pass
            assigned = False
            for t_idx in range(min_t, len(tracks)):
                if not any(n.overlaps(on) for on in tracks[t_idx]):
                    tracks[t_idx].append(n)
                    n.track = t_idx
                    assigned = True
                    break
            if not assigned:
                n.track = len(tracks)
                tracks.append([n])
            routed.append(n)
            remaining.remove(n)

    # Grid sizing
    max_x = max(n.get_x_max() for n in final_nets) if final_nets else 0
    length = max(3, len(tracks) * 2 + 1)
    size_x = max_x + 3
    size_y = 3
    # A* Sequential Routing with dynamic channel length expansion
    import random
    rng = random.Random(42)
    
    routing_success = False
    final_occupied_wires = {}
    final_occupied_supports = {}
    max_length_extension = 10  # Allow increasing length by up to 10 tracks
    
    for length_increment in range(0, max_length_extension + 1, 2):
        current_length = length + length_increment
        
        circuit = Circuit(int(size_x), size_y, current_length)
        if warn_overwrite:
            orig_set_block = circuit.set_block
            def custom_set_block(x, y, z, block):
                if (x, y, z) in circuit.blocks:
                    old = circuit.blocks[(x, y, z)]
                    if old != block:
                        print(f"WARNING: Overwriting block at ({x}, {y}, {z}) from '{old}' to '{block}'")
                orig_set_block(x, y, z, block)
            circuit.set_block = custom_set_block
            
        orderings = [sorted(nets, key=lambda n: get_net_length_heuristic(n, current_length))]
        for _ in range(200):
            shuffled = list(nets)
            rng.shuffle(shuffled)
            orderings.append(shuffled)
            
        for attempt, order in enumerate(orderings):
            occupied_wires = {}
            occupied_supports = {}
            
            # Pre-occupy all pin locations for their respective nets
            for n in nets:
                for p in n.pins:
                    z_coord = 0 if p.is_top else current_length - 1
                    occupied_wires[(p.x, 0, z_coord)] = n.id
                    
            success = True
            for n in order:
                pin_coords = []
                for p in n.pins:
                    z_coord = 0 if p.is_top else current_length - 1
                    pin_coords.append((p.x, 0, z_coord))
                    
                if not pin_coords:
                    continue
                    
                routed_coords = {pin_coords[0]}
                for next_pin in pin_coords[1:]:
                    path = find_path(next_pin, routed_coords, n.id, occupied_wires, occupied_supports, size_x, size_y, current_length, nets)
                    if path is None:
                        success = False
                        break
                    for pos in path:
                        routed_coords.add(pos)
                        occupied_wires[pos] = n.id
                        if pos[1] > 0:
                            occupied_supports[(pos[0], pos[1] - 1, pos[2])] = n.id
                if not success:
                    break
                    
            if success:
                routing_success = True
                final_occupied_wires = occupied_wires
                final_occupied_supports = occupied_supports
                length = current_length
                break
                
        if routing_success:
            break
            
    if not routing_success:
        raise ValueError("ROUTING FAILED: All routing orderings (default + 200 random shuffles) failed to find a path, even after expanding channel length!")
        
    occupied_wires = final_occupied_wires
    occupied_supports = final_occupied_supports

    # Place elements into Circuit using color-coded support blocks
    wool_types = [
        "minecraft:white_wool",
        "minecraft:orange_wool",
        "minecraft:magenta_wool",
        "minecraft:light_blue_wool",
        "minecraft:yellow_wool",
        "minecraft:lime_wool",
        "minecraft:pink_wool",
        "minecraft:gray_wool",
        "minecraft:light_gray_wool",
        "minecraft:cyan_wool",
        "minecraft:purple_wool",
        "minecraft:blue_wool",
        "minecraft:brown_wool",
        "minecraft:green_wool",
        "minecraft:red_wool",
        "minecraft:black_wool"
    ]

    for (x, y, z), nid in occupied_supports.items():
        if (x, y, z) not in occupied_wires:
            color = wool_types[nid % len(wool_types)]
            circuit.set_block(x, y, z, color)
            
    for (x, y, z), nid in occupied_wires.items():
        circuit.set_block(x, y, z, "minecraft:redstone_wire")

    return circuit

def apply_lowering(circuit):
    # Left as a no-op for compatibility as A* produces optimal lowerings directly
    pass
