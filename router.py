from logic_gates import Circuit

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

def route(nets_input, top_gates=None, bot_gates=None):
    """
    nets_input: List of lists, where each inner list contains (x, y, is_top) tuples.
    top_gates/bot_gates: Optional lists of gate objects to track occupied X-coordinates.
    Returns a Circuit object.
    """
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

    # 2. VCG and doglegs
    occupied_xs = set()
    for g in (top_gates or []):
        off = getattr(g, 'x_offset', 0)
        for x in range(off, off + g.size_x): occupied_xs.add(x)
    for g in (bot_gates or []):
        off = getattr(g, 'x_offset', 0)
        for x in range(off, off + g.size_x): occupied_xs.add(x)
    for n in nets:
        for p in n.pins: occupied_xs.add(p.x)

    x_map = {}
    for n in nets:
        for p in n.pins:
            if p.x not in x_map: x_map[p.x] = {'top': set(), 'bot': set()}
            if p.is_top: x_map[p.x]['top'].add(n.id)
            else: x_map[p.x]['bot'].add(n.id)

    adj = {n.id: set() for n in nets}
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

    final_nets = list(nets)
    for x in sorted(list(x_map.keys())):
        tops, bots = x_map[x]['top'], x_map[x]['bot']
        for t in tops:
            for b in bots:
                if t != b:
                    if has_path(t, b):
                        dog_id = t + 50000
                        t_net = next(n for n in nets if n.id == t)
                        
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

    # 3. Straight Nets and Track Assignment
    remaining = list(final_nets)
    straight_nets = []
    
    # Identify straight nets (no horizontal span and no dependencies)
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
                    pass # Probably a straight net
                    
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

    # 4. Circuit Generation
    max_x = max(n.get_x_max() for n in final_nets) if final_nets else 0
    length = len(tracks) * 2 + 1
    circuit = Circuit(int(max_x + 1), 3, length)
    
    occupied_xyz = {} # (x, y, z) -> nid
    def check_adj(x, y, z, nid):
        for dx in [-1, 1]:
            if (x+dx, y, z) in occupied_xyz:
                other_nid = occupied_xyz[(x+dx, y, z)]
                if other_nid != nid:
                    # Allow adjacency ONLY if one is a dogleg partner of the other
                    is_partner = False
                    for n_obj in final_nets:
                        if n_obj.id == nid:
                            if n_obj.out_partner and n_obj.out_partner.id == other_nid: is_partner = True
                        if n_obj.id == other_nid:
                            if n_obj.out_partner and n_obj.out_partner.id == nid: is_partner = True
                    
                    if not is_partner:
                        raise Exception(f"SHORT: {nid} & {other_nid} at x={x}/{x+dx}, y={y}, z={z}")
        occupied_xyz[(x, y, z)] = nid

    # Draw Straight Nets
    for n in straight_nets:
        for z in range(length):
            circuit.set_block(int(n.get_x_min()), 0, z, "minecraft:redstone_wire")
            check_adj(int(n.get_x_min()), 0, z, n.id)

    # Draw Track Nets
    for t_idx, track_nets in enumerate(tracks):
        zt = t_idx * 2 + 1
        for n in track_nets:
            xmin, xmax = int(n.get_x_min()), int(n.get_x_max())
            blen = xmax - xmin + 1
            color = "minecraft:red_wool" if blen <= 4 else "minecraft:light_gray_wool"
            txs = {p.x for p in n.pins if p.is_top}
            bxs = {p.x for p in n.pins if not p.is_top}
            dxs = {int(n.dogleg_x)} if n.dogleg_x != -1 else set()
            
            for x in range(xmin, xmax + 1):
                if blen <= 4:
                    circuit.set_block(x, 0, zt, "minecraft:redstone_wire")
                    check_adj(x, 0, zt, n.id)
                elif x in txs:
                    circuit.set_block(x, 0, zt, "minecraft:cyan_wool")
                    circuit.set_block(x, 1, zt, "minecraft:redstone_wire")
                    check_adj(x, 1, zt, n.id)
                elif x in bxs:
                    circuit.set_block(x, 0, zt, "minecraft:pink_wool")
                    circuit.set_block(x, 1, zt, "minecraft:redstone_wire")
                    check_adj(x, 1, zt, n.id)
                elif x in dxs:
                    circuit.set_block(x, 0, zt, "minecraft:yellow_wool")
                    circuit.set_block(x, 1, zt, "minecraft:redstone_wire")
                    check_adj(x, 1, zt, n.id)
                else:
                    circuit.set_block(x, 1, zt, color)
                    circuit.set_block(x, 2, zt, "minecraft:redstone_wire")
                    check_adj(x, 2, zt, n.id)
                
            for p in n.pins:
                zs = zt - 1 if p.is_top else zt + 1
                circuit.set_block(p.x, 0, zs, "minecraft:redstone_wire")
                check_adj(p.x, 0, zs, n.id)
            if n.outpath:
                circuit.set_block(int(n.dogleg_x), 0, zt + 1, "minecraft:redstone_wire")
                check_adj(int(n.dogleg_x), 0, zt + 1, n.id)
            if n.out_partner and not n.outpath:
                circuit.set_block(int(n.dogleg_x), 0, zt - 1, "minecraft:redstone_wire")
                check_adj(int(n.dogleg_x), 0, zt - 1, n.id)

    # Draw vertical runs for Track Nets
    for track_nets in tracks:
        for n in track_nets:
            zt = n.track * 2 + 1
            for p in n.pins:
                if p.is_top:
                    for z in range(0, zt - 1):
                        circuit.set_block(p.x, 0, z, "minecraft:redstone_wire")
                        check_adj(p.x, 0, z, n.id)
                else:
                    for z in range(zt + 2, length):
                        circuit.set_block(p.x, 0, z, "minecraft:redstone_wire")
                        check_adj(p.x, 0, z, n.id)
            if n.outpath:
                zs = zt + 2
                ze = n.out_partner.track * 2 + 1 - 1
                for z in range(zs, ze + 1):
                    circuit.set_block(int(n.dogleg_x), 0, z, "minecraft:redstone_wire")
                    check_adj(int(n.dogleg_x), 0, z, n.id)

    apply_lowering(circuit)
    return circuit

def apply_lowering(circuit):
    blocks = circuit.blocks
    lg_wool = [(x, z) for (x, y, z), b in blocks.items() if y == 1 and b == "minecraft:light_gray_wool"]
    segs_by_z = {}
    for x, z in sorted(lg_wool, key=lambda p: (p[1], p[0])):
        if z not in segs_by_z: segs_by_z[z] = [[x, x]]
        else:
            last = segs_by_z[z][-1]
            if x == last[1] + 1: last[1] = x
            else: segs_by_z[z].append([x, x])
            
    lowered_segs = []
    for z, segs in segs_by_z.items():
        for xmin, xmax in segs:
            if all((x, 0, z) not in blocks for x in range(xmin, xmax + 1)):
                lowered_segs.append((xmin, xmax, z))
                
    specials = [(x, z) for (x, y, z), b in blocks.items() if y == 0 and b in ["minecraft:cyan_wool", "minecraft:pink_wool", "minecraft:yellow_wool"]]
    lowered_specials = []
    
    # Store lowered segment bounds as tuples for reliable comparison
    ls_bounds = {(ls[0], ls[1], ls[2]) for ls in lowered_segs}
    
    for sx, sz in specials:
        # Find all bridges (segs) that touch this special block at sx
        # If ALL bridge segments touching this pin were lowered, we can lower the pin too.
        all_touching = [tuple(s) for s in segs_by_z.get(sz, []) if s[0] == sx + 1 or s[1] == sx - 1]
        
        if all_touching and all((s[0], s[1], sz) in ls_bounds for s in all_touching):
            lowered_specials.append((sx, sz))
            
    # Apply lowering for bridges
    for xmin, xmax, z in lowered_segs:
        for x in range(xmin, xmax + 1):
            wire = blocks.get((x, 2, z), "minecraft:redstone_wire")
            blocks[(x, 0, z)] = wire
            if (x, 1, z) in blocks: del blocks[(x, 1, z)]
            if (x, 2, z) in blocks: del blocks[(x, 2, z)]
            
    # Apply lowering for hump starts (cyan/pink/yellow)
    for sx, sz in lowered_specials:
        # The wire was at y=1, we move it to y=0 (replacing the wool)
        wire = blocks.get((sx, 1, sz), "minecraft:redstone_wire")
        blocks[(sx, 0, sz)] = wire
        if (sx, 1, sz) in blocks: del blocks[(sx, 1, sz)]
