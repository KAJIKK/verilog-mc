import mcschematic
import re
from collections import deque
import sys
import nbtlib
import os
import time
import shutil

def parse_state(state):
    """
    Parses a Minecraft block state string into a block ID and a dictionary of properties.
    Example: 'minecraft:redstone_wire[power=15,north=side]' -> ('minecraft:redstone_wire', {'power': '15', 'north': 'side'})
    """
    match = re.match(r"([^\[]+)(?:\[(.*)\])?", state)
    if not match: return state, {}
    block_id, props = match.group(1), {}
    if match.group(2):
        for pair in match.group(2).split(","):
            if "=" in pair:
                k, v = pair.split("=")
                props[k] = v
    return block_id, props

def get_offset(d):
    """
    Returns the (x, y, z) coordinate offset for a given Minecraft direction.
    """
    return {"north":(0,0,-1), "south":(0,0,1), "east":(1,0,0), "west":(-1,0,0), "up":(0,1,0), "down":(0,-1,0)}[d]

def get_opposite(d):
    """
    Returns the opposite direction of the given Minecraft direction.
    """
    return {"north":"south", "south":"north", "east":"west", "west":"east", "up":"down", "down":"up"}[d]

def get_connections(pos, state, block_map):
    """
    Calculates all valid redstone wire connections for a given position.
    Handles horizontal connections ('side'), climbing connections ('up'), 
    and descending connections to wires below.
    """
    bid, props = parse_state(state)
    conns = []
    if "redstone_wire" in bid:
        # Check horizontal and climbing connections
        for d in ["north", "south", "east", "west"]:
            val = props.get(d, "none")
            if val == "side": conns.append((d, 0))
            elif val == "up": conns.append((d, 1))
        # Check descending connections (neighbor block is 1 block lower)
        for d in ["north", "south", "east", "west"]:
            off = get_offset(d)
            npos_down = (pos[0]+off[0], pos[1]-1, pos[2]+off[2])
            if npos_down in block_map:
                nstate = block_map[npos_down]
                nbid, nprops = parse_state(nstate)
                if "redstone_wire" in nbid and nprops.get(get_opposite(d)) == "up":
                    conns.append((d, -1))
    return conns

def is_eligible(pos, block_map):
    """
    Determines if a block is eligible for repeater placement.
    Requires exactly two opposite connections (straight line).
    If a connection is 'up', it's valid. If 'side', the adjacent block must be a redstone wire.
    """
    state = block_map.get(pos)
    if not state: return False
    bid, props = parse_state(state)
    if "redstone_wire" not in bid: return False
    
    active = []
    for d in ["north", "south", "east", "west"]:
        if props.get(d) in ["side", "up"]:
            active.append(d)
    
    # First check for opposite connections (if not straight, return false)
    if len(active) != 2:
        return False
    d1, d2 = active
    if d2 != get_opposite(d1):
        return False
        
    # Then for the two ends
    for d in [d1, d2]:
        val = props.get(d)
        if val == "up":
            return False # Repeaters cannot climb or descend like dust.
        elif val == "side":
            # check the block next to it
            off = get_offset(d)
            npos = (pos[0] + off[0], pos[1], pos[2] + off[2])
            nstate = block_map.get(npos)
            if not nstate:
                return False
            nbid, _ = parse_state(nstate)
            if "redstone_wire" not in nbid:
                return False
                
    # Then check for potential shorts caused by powering adjacent nets through solid blocks
    for d in [d1, d2]:
        off = get_offset(d)
        B = (pos[0] + off[0], pos[1], pos[2] + off[2])
        state_B = block_map.get(B)
        
        def is_solid(state_str):
            if not state_str: return False
            b_id, _ = parse_state(state_str)
            non_solids = ["air", "redstone_wire", "repeater", "torch", "lever", "sign"]
            return not any(ns in b_id for ns in non_solids)
            
        if is_solid(state_B):
            # Scan 5 sides of B (excluding Up and the source pos)
            sides = [
                (0, -1, 0),  # down
                (0, 0, -1),  # north
                (0, 0, 1),   # south
                (1, 0, 0),   # east
                (-1, 0, 0)   # west
            ]
            for ox, oy, oz in sides:
                S_pos = (B[0] + ox, B[1] + oy, B[2] + oz)
                if S_pos == pos:
                    continue
                state_S = block_map.get(S_pos)
                if state_S and "redstone_wire" in state_S:
                    # Check if there is a block on top of S_pos
                    top_pos = (S_pos[0], S_pos[1] + 1, S_pos[2])
                    state_top = block_map.get(top_pos)
                    if state_top and "air" not in state_top:
                        return False
                        
    # if no check failed return true
    return True

def find_sources(block_map):
    """
    Finds all initial redstone power sources (levers) in the block map.
    Returns a list of (pos, power, direction) tuples.
    """
    sources = []
    for pos, state in block_map.items():
        bid, props = parse_state(state)
        if "lever" in bid:
            face = props.get("face", "floor")
            facing = props.get("facing")
            
            attached_pos = None
            if face == "floor": attached_pos = (pos[0], pos[1]-1, pos[2])
            elif face == "ceiling": attached_pos = (pos[0], pos[1]+1, pos[2])
            elif face == "wall":
                off = get_offset(get_opposite(facing))
                attached_pos = (pos[0]+off[0], pos[1], pos[2]+off[2])
            
            s_list = [pos]
            if attached_pos: s_list.append(attached_pos)
            
            for s_pos in s_list:
                for d in ["north", "south", "east", "west", "up", "down"]:
                    off = get_offset(d)
                    npos = (s_pos[0]+off[0], s_pos[1]+off[1], s_pos[2]+off[2])
                    if npos in block_map:
                        nstate = block_map[npos]
                        nbid, nprops = parse_state(nstate)
                        if "redstone_wire" in nbid:
                            if nprops.get(get_opposite(d)) in ["side", "up"]:
                                sources.append((npos, 15, d))
    return sources

def load_schematic(path):
    """
    Loads a .schem file, handles WorldEdit offsets, and returns its dimensions and block map.
    """
    nbt = nbtlib.load(path)
    root = nbt.root if hasattr(nbt, 'root') else nbt
    w, h, l = 0, 0, 0
    temp_path = None
    if 'Schematic' in root:
        s = root['Schematic']
        w, h, l = int(s['Width']), int(s['Height']), int(s['Length'])
        b = s['Blocks']
        fixed_nbt = nbtlib.Compound({
            'Version': s['Version'], 'DataVersion': s['DataVersion'],
            'Metadata': nbtlib.Compound({'WEOffsetX': nbtlib.Int(0), 'WEOffsetY': nbtlib.Int(0), 'WEOffsetZ': nbtlib.Int(0)}),
            'Width': s['Width'], 'Height': s['Height'], 'Length': s['Length'],
            'Palette': b['Palette'], 'BlockData': b['Data'], 'BlockEntities': b.get('BlockEntities', nbtlib.List([]))
        })
        temp_path = f"temp_{os.path.basename(path)}"
        nbtlib.File(fixed_nbt).save(temp_path, gzipped=True)
        schem = mcschematic.MCSchematic(temp_path)
    else:
        w, h, l = int(root.get('Width', 0)), int(root.get('Height', 0)), int(root.get('Length', 0))
        schem = mcschematic.MCSchematic(path)
        
    block_map = {}
    for y in range(h):
        for z in range(l):
            for x in range(w):
                state = schem.getBlockStateAt((x, y, z))
                if state != "minecraft:air":
                    block_map[(x, y, z)] = state
                    
    if temp_path and os.path.exists(temp_path):
        os.remove(temp_path)
        
    return w, h, l, block_map, schem

def get_score(block_map, sources, repeaters):
    """
    Simulates the redstone network and returns the total sum of power levels.
    Pro kubu: tohle by se nejspíš mělo vylepšit. ještě to negeneruje uplně optimální řešení
    omezit sčítání powerů na pouze jeden graf a ne celý obvod
    """
    powers = {}
    queue = deque()
    
    for src_pos, power, d in sources:
        powers[src_pos] = 15
        queue.append((src_pos, 15))
        
    while queue:
        pos, pwr = queue.popleft()
        
        if pwr < powers.get(pos, -1):
            continue
            
        if pwr > 0:
            state = block_map.get(pos)
            if not state: continue
            conns = get_connections(pos, state, block_map)
            for direction, y_off in conns:
                off = get_offset(direction)
                npos = (pos[0] + off[0], pos[1] + y_off, pos[2] + off[2])
                
                if npos in block_map:
                    npwr = pwr - 1
                    if npos in repeaters:
                        npwr = 15
                        
                    if npwr > powers.get(npos, -1):
                        powers[npos] = npwr
                        queue.append((npos, npwr))
    return sum(powers.values())
    #return sum(1 for v in powers.values() if v > 0)

def get_downstream(start_node, graph):
    """
    Finds all nodes reachable from the start_node using established graph connections.
    """
    downstream = set()
    stack = [start_node]
    while stack:
        node = stack.pop()
        if node in graph:
            for npos in graph[node]['connections']:
                if npos not in downstream:
                    downstream.add(npos)
                    stack.append(npos)
    return downstream

def build_graph_baseline(block_map, sources):
    """Restore long lines with directional repeaters on flat straight dust.

    Rebuild power after each placement rather than resetting an undirected
    downstream graph (which could reset its own repeater and loop forever).
    A line without a reachable legal repeater site is an explicit error.
    """
    print(f"Building graphs for {len(sources)} sources...")
    directions = {name: get_offset(get_opposite(name)) for name in ('north', 'south', 'east', 'west')}
    signals = {}
    for pos, block in block_map.items():
        bid, props = parse_state(block)
        if bid == 'minecraft:redstone_wire':
            signals[pos] = None
        elif bid == 'minecraft:repeater':
            dx, _, dz = directions[props.get('facing', 'north')]
            signals[pos] = (dx, dz)
    solids = {pos for pos, block in block_map.items() if pos not in signals and
              not any(name in block for name in ('air', 'torch', 'lever', 'sign'))}
    from redstone_geometry import signal_neighbors, signal_powers, FACING

    def topology(source):
        parents = {source: None}
        queue = deque([source])
        while queue:
            pos = queue.popleft()
            for neighbor in signal_neighbors(pos, signals, solids):
                if neighbor not in parents:
                    parents[neighbor] = pos
                    queue.append(neighbor)
        return parents

    repeaters = {}
    source_positions = {pos for pos, _, _ in sources}
    required = {}
    for pos, _, _ in sources:
        if pos in signals:
            required[pos] = set(topology(pos))
    for index, (source, source_power, _) in enumerate(sources):
        print(f"Processing source {index+1}/{len(sources)} at {source}")
        if source not in signals:
            continue
        # Every iteration must add a distinct repeater: finite even for loops.
        for _ in range(len(signals) + 1):
            parents = topology(source)
            powers = signal_powers(signals, solids, source, source_power)
            if not required[source].issubset(parents):
                raise ValueError(f'Repeater direction disconnected a branch from {source}')
            unpowered = [pos for pos in parents if powers.get(pos, 0) == 0]
            if not unpowered:
                break
            target = unpowered[0]
            path = []
            while target is not None:
                path.append(target)
                target = parents[target]
            path.reverse()
            placed = False
            for j in range(len(path)-2, 0, -1):
                pos = path[j]
                before, after = path[j-1], path[j+1]
                if (pos in source_positions or signals[pos] is not None or
                        powers.get(pos, 0) == 0 or not is_eligible(pos, block_map)):
                    continue
                delta = (after[0]-pos[0], after[2]-pos[2])
                if before != (pos[0]-delta[0], pos[1], pos[2]-delta[1]) or after[1] != pos[1]:
                    continue
                signals[pos] = delta
                repeaters[pos] = FACING[delta]
                placed = True
                break
            if not placed:
                raise ValueError(f'No powered flat straight repeater site before {path[-1]} '
                                 f'from {source}; add a landing to this route')
        else:
            raise ValueError(f'Repeater placement did not converge from {source}')
    final_graph = {}
    for source, source_power, _ in sources:
        if source not in signals:
            continue
        powers = signal_powers(signals, solids, source, source_power)
        if any(powers.get(pos, 0) == 0 for pos in required[source]):
            raise ValueError(f'A later repeater broke an earlier source route at {source}')
        for pos, power in powers.items():
            entry = final_graph.setdefault(pos, {'pos': pos, 'power': 0,
                'connections': list(signal_neighbors(pos, signals, solids)),
                'is_eligible': is_eligible(pos, block_map)})
            entry['power'] = max(entry['power'], power)
    return final_graph, repeaters


def _tree_repeaters(signals, parents, order, source_power, eligible, prefer_early=False):
    """Minimum added repeaters on a rooted electrical tree, in O(16 * wires).

    A state is the power dust would have at a node. State zero can still host
    a repeater: its preceding dust has power one, sufficient to drive it.
    Repeaters restore their output dust to 15 without a dust-to-dust loss.
    """
    children = {p: [] for p in order}
    for p in order[1:]:
        children[parents[p]].append(p)
    infinity = len(order)+1
    costs, placements = {}, {}
    for p in reversed(order):
        child_costs = [costs[c] for c in children[p]]
        restored = sum(table[15] for table in child_costs)
        if signals[p] is not None:
            costs[p] = [restored]*16
            continue
        keep = [infinity]+[sum(table[power-1] for table in child_costs)
                           for power in range(1,16)]
        # Candidate direction must follow the tree; no turns, branches, slopes,
        # source pins, or existing gate components may be replaced.
        if p in eligible and parents[p] is not None and len(children[p]) == 1:
            before,after = parents[p],children[p][0]
            delta = (after[0]-p[0],after[2]-p[2])
            if before == (p[0]-delta[0],p[1],p[2]-delta[1]) and after[1] == p[1]:
                placements[p] = (1+restored,delta)
                costs[p] = [min(value,1+restored) for value in keep]
                continue
        costs[p] = keep
    if costs[order[0]][source_power] >= infinity:
        raise ValueError(f'No powered flat straight repeater site from {order[0]}; '
                         'add a landing to this route')
    result = {}
    pending = [(order[0],source_power)]
    while pending:
        p,power = pending.pop()
        fixed = signals[p] is not None
        candidate = placements.get(p)
        keep = (sum(costs[c][power-1] for c in children[p]) if power > 0 else infinity)
        replace = (not fixed and candidate is not None and
                   (candidate[0] < keep or (prefer_early and candidate[0] == keep)))
        if replace:
            result[p] = candidate[1]
        child_power = 15 if fixed or replace else power-1
        pending.extend((c,child_power) for c in children[p])
    return result


def _repeater_feedback(signals, solids, added):
    """Detect sustainable feedback, including attenuation around dust cycles.

    Dust-only cycles decay after switch-off. A directional cycle containing a
    repeater can latch on; ordinary source-on reachability cannot detect that.
    Existing gate feedback is preserved, but restoration must not create it.
    """
    from redstone_geometry import signal_neighbors,signal_powers
    for repeater in added:
        dx,dz = signals[repeater]
        input_pos = (repeater[0]-dx,repeater[1],repeater[2]-dz)
        # Energize ONLY this repeater, with all external sources absent. If its
        # output (possibly through other repeaters) powers its input, it latches.
        # A long dust-only return path can decay to zero and is entirely safe.
        powers = signal_powers(signals,solids,repeater)
        if (powers.get(input_pos,0) > 0 and
                repeater in signal_neighbors(input_pos,signals,solids)):
            return repeater
    return None


def build_graph(block_map, sources):
    """Minimize independent trees; compare cyclic heuristics and prune shared nets.

    Gate repeaters are immutable. Every originally reachable signal block must
    remain powered from EACH original source, not merely from their union.
    The original greedy algorithm remains available as build_graph_baseline.
    """
    from redstone_geometry import signal_neighbors, signal_powers, FACING
    directions = {name: get_offset(get_opposite(name)) for name in ('north','south','east','west')}
    signals = {}
    for p,block in block_map.items():
        bid,props = parse_state(block)
        if bid == 'minecraft:redstone_wire':
            signals[p] = None
        elif bid == 'minecraft:repeater':
            dx,_,dz = directions[props.get('facing','north')]
            signals[p] = (dx,dz)
    solids = {p for p,block in block_map.items() if p not in signals and
              not any(name in block for name in ('air','torch','lever','sign'))}
    adjacency = {p:tuple(signal_neighbors(p,signals,solids)) for p in signals}
    source_positions = {p for p,_,_ in sources}
    eligible = {p for p,value in signals.items()
                if value is None and p not in source_positions and is_eligible(p,block_map)}
    routes,owners = [],{}
    for source,power,_ in sources:
        if source not in signals:
            continue
        if not 1 <= power <= 15:
            raise ValueError('Source power must be between 1 and 15')
        parents,order,tree = {source:None},[source],True
        for p in order:
            for q in adjacency[p]:
                if q not in parents:
                    parents[q] = p
                    order.append(q)
                elif parents[p] != q and parents[q] != p:
                    tree = False
        index = len(routes)
        routes.append((source,power,parents,order,tree))
        for p in order:
            owners.setdefault(p,[]).append(index)

    added, prunable, fallback_sources = {},{},[]
    for source,power,parents,order,tree in routes:
        if all(len(owners[p]) == 1 for p in order):
            # On a cycle this optimizes a spanning tree, not the entire graph.
            # Favor a tied shared upstream placement over boosting a loop arm.
            if tree:
                added.update(_tree_repeaters(signals,parents,order,power,eligible))
                continue
            options = []
            try:
                options.append(_tree_repeaters(signals,parents,order,power,eligible,True))
            except ValueError:
                pass
            try:
                _,greedy = build_graph_baseline(block_map,[(source,power,'south')])
                inverse = {facing:delta for delta,facing in FACING.items()}
                options.append({p:inverse[facing] for p,facing in greedy.items()})
            except ValueError:
                pass
            for candidate in sorted(options,key=len):
                trial = signals.copy()
                trial.update(candidate)
                powers = signal_powers(trial,solids,source,power)
                if (all(powers.get(p,0) > 0 for p in parents) and
                        _repeater_feedback(trial,solids,candidate) is None):
                    added.update(candidate)
                    prunable.update({p:FACING[d] for p,d in candidate.items()})
                    break
            else:
                raise ValueError(f'No feedback-free restoration found for cyclic route from {source}')
        else:
            fallback_sources.append((source,power,'south'))
    if fallback_sources:
        _,greedy = build_graph_baseline(block_map,fallback_sources)
        prunable.update(greedy)
        inverse = {facing:delta for delta,facing in FACING.items()}
        added.update({p:inverse[facing] for p,facing in greedy.items()})
    signals.update(added)
    # Shared roots and cycles are not trees. Remove a greedy insertion only if
    # every affected root still powers its entire original reachable network.
    for p in sorted(prunable):
        direction = signals[p]
        signals[p] = None
        for index in owners[p]:
            source,power,parents,_,_ = routes[index]
            powers = signal_powers(signals,solids,source,power)
            if any(powers.get(q,0) == 0 for q in parents):
                signals[p] = direction
                break
        else:
            if _repeater_feedback(signals,solids,(q for q in added if q != p)) is None:
                del added[p]
            else:
                signals[p] = direction
    feedback = _repeater_feedback(signals,solids,added)
    if feedback is not None:
        raise ValueError(f'Repeater would create self-sustaining feedback at {feedback}; '
                         'split the loop into directional branches')
    final_graph = {}
    for source,power,parents,_,_ in routes:
        powers = signal_powers(signals,solids,source,power)
        if any(powers.get(p,0) == 0 for p in parents):
            raise ValueError(f'Repeater placement broke a source route at {source}')
        for p,value in powers.items():
            entry = final_graph.setdefault(p,{'pos':p,'power':0,
                'connections':list(signal_neighbors(p,signals,solids)),
                'is_eligible':p in eligible})
            entry['power'] = max(entry['power'],value)
    return final_graph,{p:FACING[direction] for p,direction in added.items()}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 main_gemini.py <path_to_schematic>")
        sys.exit(1)
    
    schem_path = sys.argv[1]
    print(f"Loading schematic: {schem_path}")
    width, height, length, block_map, schem = load_schematic(schem_path)
    print(f"Schematic loaded. Dimensions: {width}x{height}x{length}")
    
    sources = find_sources(block_map)
    print(f"Found {len(sources)} sources.")
    
    start_time = time.time()
    graph, repeaters = build_graph(block_map, sources)
    end_time = time.time()
    print(f"Graph built with {len(repeaters)} repeaters. Time: {end_time - start_time:.4f}s")
    
    # Save the modified schematic
    for pos, direction in repeaters.items():
        schem.setBlock(pos, f"minecraft:repeater[facing={direction}]")
    
    output_filename = "output"
    schem.save(".", output_filename, mcschematic.Version.JE_1_20_1)
    print(f"Schematic saved to {output_filename}.schem")
    
    # Export to WorldEdit directory
    target_dir = "/home/kajat/.local/share/PrismLauncher/instances/Fabulously Optimized(1)/minecraft/config/worldedit/schematics/repeaters"
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, "output.schem")
    shutil.copy("output.schem", target_path)
    print(f"Schematic exported to: {target_path}")
    
    # Create visited map for power rendering
    visited = {pos: data['power'] for pos, data in graph.items()}
    
    # print("Initializing Pygame visualization...")
    # render_layer(width, height, length, 0, block_map, visited, repeaters, graph=graph)
