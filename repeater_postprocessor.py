import mcschematic
import re
from collections import deque
try:
    import pygame
except ImportError:
    pygame = None
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

def is_eligible(pos, block_map): # do not touch this, this is confiremed to be correct
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
            continue # it's good and go to the other one
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

def build_graph(block_map, sources):
    """
    Builds a directed graph representing redstone flow from sources.
    Uses BFS to track power, backtracks to place repeaters when power hits 0.
    """
    print(f"Building graphs for {len(sources)} sources...")
    final_graph = {}
    global_repeaters = {}
    processed_count = 0

    for i, source in enumerate(sources):
        src_pos, _, _ = source
        print(f"Processing source {i+1}/{len(sources)} at {src_pos}")
        
        # Local graph for this source
        graph = {}
        queue = deque()
        
        graph[src_pos] = {
            'pos': src_pos,
            'is_eligible': is_eligible(src_pos, block_map),
            'connections': [],
            'power': 15
        }
        queue.append((src_pos, 15, [src_pos]))
        
        while queue:
            pos, power, path = queue.popleft()
            processed_count += 1

            state = block_map.get(pos)
            if not state: continue
            
            if power < graph[pos]['power']:
                continue
                
            if power == 0:
                # Backtrack to find repeater placement using scoring
                best_score = -1
                best_rp = None
                best_dir = None
                
                for j in range(len(path) - 1, -1, -1):
                    rp = path[j]
                    if is_eligible(rp, block_map):
                        # Determine direction
                        dx, dz = 0, 0
                        if j + 1 < len(path):
                            next_p = path[j+1]
                            dx, dz = next_p[0] - rp[0], next_p[2] - rp[2]
                        elif j > 0:
                            prev_p = path[j-1]
                            dx, dz = rp[0] - prev_p[0], rp[2] - prev_p[2]
                            
                        direction = None
                        if dx == 1: direction = "west"
                        elif dx == -1: direction = "east"
                        elif dz == 1: direction = "north"
                        elif dz == -1: direction = "south"
                        
                        if direction:
                            # Reuse existing global repeater if possible
                            if rp in global_repeaters and global_repeaters[rp] == direction:
                                best_rp, best_dir, best_score = rp, direction, float('inf')
                                break
                                
                            if rp not in global_repeaters:
                                test_repeaters = global_repeaters.copy()
                                test_repeaters[rp] = direction
                                # Evaluate score ONLY for this source
                                score = get_score(block_map, [source], test_repeaters)
                                
                                if score > best_score:
                                    best_score, best_rp, best_dir = score, rp, direction
                                elif score < best_score and best_score != -1:
                                    # Optimization: score usually increases then decreases as we backtrack
                                    break
                                    
                if best_rp:
                    global_repeaters[best_rp] = best_dir
                    graph[best_rp]['power'] = 15
                    
                    # Reset downstream in the local graph
                    downstream = get_downstream(best_rp, graph)
                    for d_pos in downstream:
                        if d_pos in graph:
                            graph[d_pos]['power'] = -1
                            graph[d_pos]['connections'] = []
                    
                    # Clean main queue of downstream nodes
                    new_queue = deque()
                    for q_pos, q_pwr, q_path in queue:
                        if q_pos not in downstream:
                            new_queue.append((q_pos, q_pwr, q_path))
                    queue = new_queue
                    
                    queue.append((best_rp, 15, [best_rp]))
                    continue
            
            if power > 0:
                conns = get_connections(pos, state, block_map)
                for direction, y_off in conns:
                    off = get_offset(direction)
                    npos = (pos[0] + off[0], pos[1] + y_off, pos[2] + off[2])
                    
                    if npos in block_map:
                        n_power = power - 1
                        # Boost power if there's an existing repeater
                        if npos in global_repeaters:
                            n_power = 15
                            
                        if npos not in graph:
                            graph[npos] = {
                                'pos': npos,
                                'is_eligible': is_eligible(npos, block_map),
                                'connections': [],
                                'power': -1
                            }
                        
                        if n_power >= graph[npos]['power']:
                            if npos not in graph[pos]['connections']:
                                graph[pos]['connections'].append(npos)
                            
                            if n_power > graph[npos]['power']:
                                graph[npos]['power'] = n_power
                                queue.append((npos, n_power, path + [npos]))

        # Merge local graph into final_graph
        for p, data in graph.items():
            if p not in final_graph:
                final_graph[p] = {
                    'pos': p,
                    'is_eligible': data['is_eligible'],
                    'connections': list(data['connections']),
                    'power': data['power']
                }
            else:
                final_graph[p]['power'] = max(final_graph[p]['power'], data['power'])
                for c in data['connections']:
                    if c not in final_graph[p]['connections']:
                        final_graph[p]['connections'].append(c)

    return final_graph, global_repeaters

def draw_arrow(screen, color, rect, direction):
    """
    Draws a directional arrow inside a cell to indicate repeater orientation.
    """
    # Directions: north, south, east, west
    cx, cy = rect.center
    s = rect.width // 4
    if direction == "north":
        pts = [(cx, cy + s), (cx - s, cy - s), (cx + s, cy - s)]
    elif direction == "south":
        pts = [(cx, cy - s), (cx - s, cy + s), (cx + s, cy + s)]
    elif direction == "east":
        pts = [(cx - s, cy), (cx + s, cy - s), (cx + s, cy + s)]
    elif direction == "west":
        pts = [(cx + s, cy), (cx - s, cy - s), (cx - s, cy + s)]
    else:
        return
    pygame.draw.polygon(screen, color, pts)

def render_layer(width, height, length, initial_layer, block_map, visited, repeaters, graph=None):
    """
    Initializes and runs the Pygame visualization loop.
    Allows navigating layers with UP/DOWN and prints coordinates on click.
    """
    pygame.init()
    cell_size = 40
    screen = pygame.display.set_mode((width * cell_size, length * cell_size))
    font = pygame.font.SysFont("Arial", 12)
    
    layer_idx = initial_layer
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP:
                    layer_idx = min(height - 1, layer_idx + 1)
                elif event.key == pygame.K_DOWN:
                    layer_idx = max(0, layer_idx - 1)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = pygame.mouse.get_pos()
                gx, gz = mx // cell_size, my // cell_size
                if 0 <= gx < width and 0 <= gz < length:
                    print(f"Clicked Block: ({gx}, {layer_idx}, {gz})")
        
        pygame.display.set_caption(f"Layer {layer_idx} / {height-1}")
        screen.fill((30, 30, 30))
        for z in range(length):
            for x in range(width):
                pos = (x, layer_idx, z)
                state = block_map.get(pos, "air")
                bid, _ = parse_state(state)
                
                rect = pygame.Rect(x * cell_size, z * cell_size, cell_size - 1, cell_size - 1)
                color = (50, 50, 50)
                
                if pos in repeaters:
                    color = (0, 255, 0)
                elif "redstone_wire" in bid:
                    power = visited.get(pos, None)
                    if power is None:
                        color = (0, 0, 0)
                    elif power > 0:
                        intensity = int(max(0, min(255, (power / 15.0) * 255)))
                        color = (intensity, 0, 0)
                    else: # power <= 0
                        intensity = int(max(0, min(255, (abs(power) / 15.0) * 255)))
                        color = (0, 0, intensity)
                elif "lever" in bid:
                    color = (200, 200, 0)
                elif "air" not in bid:
                    color = (100, 100, 100)
                
                pygame.draw.rect(screen, color, rect)
                
                if graph and pos in graph:
                    node = graph[pos]
                    if node['is_eligible']:
                        pygame.draw.rect(screen, (255, 255, 0), rect, 2)
                    for npos in node['connections']:
                        if npos[1] == layer_idx:
                            start_center = (x * cell_size + cell_size // 2, z * cell_size + cell_size // 2)
                            end_center = (npos[0] * cell_size + cell_size // 2, npos[2] * cell_size + cell_size // 2)
                            pygame.draw.line(screen, (255, 150, 150), start_center, end_center, 2)
                
                if pos in repeaters:
                    draw_arrow(screen, (0, 100, 0), rect, repeaters[pos])
                
                p_val = 0 if pos in repeaters else visited.get(pos, None)
                if p_val is not None:
                    txt = font.render(str(p_val), True, (255, 255, 255))
                    screen.blit(txt, (x * cell_size + 2, z * cell_size + 2))
        
        pygame.display.flip()
    pygame.quit()

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
