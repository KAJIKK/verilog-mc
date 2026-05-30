import math

class Pin:
    def __init__(self, x, top):
        self.x = x
        self.top = top
        self.net_id = -1
        self.is_empty = False

    def set_net(self, net_id, out_net):
        if not out_net and self.net_id != -1:
            raise Exception("Should not assign pin to two different nets")
        self.net_id = net_id

class EmptyPin(Pin):
    def __init__(self, x, top):
        super().__init__(x, top)
        self.is_empty = True
        
    def set_net(self, net_id, out_net):
        raise Exception("Cant set net of empty pin")

class PinPair:
    def __init__(self, x):
        self.top = EmptyPin(x, True)
        self.bot = EmptyPin(x, False)

class PinsArray:
    def __init__(self):
        self.pairs = []
        
    def add_pin(self, p, top):
        index = p.x // 2
        diff = index - len(self.pairs)
        if diff >= 0:
            for i in range(diff):
                self.pairs.append(PinPair(len(self.pairs) * 2))
            new_pair = PinPair(len(self.pairs) * 2)
            if top: new_pair.top = p
            else: new_pair.bot = p
            self.pairs.append(new_pair)
        else:
            pair = self.pairs[index]
            if top:
                if pair.top.is_empty: pair.top = p
                else: raise Exception("Overwrite top pin")
            else:
                if pair.bot.is_empty: pair.bot = p
                else: raise Exception("Overwrite bot pin")
                
    def add_empty_pair(self):
        x = len(self.pairs) * 2
        self.pairs.append(PinPair(x))
        return x

class GatePins:
    def __init__(self, g, v, offset, top):
        self.vertex = v
        self.offset = offset
        self.top = top
        self.gate_width = g.size_x
        self.pins = []
        self.next_free_input_pin = 0
        
        if top:
            # Use custom offsets if provided, otherwise default to spacing
            offsets = getattr(g, 'output_offsets', None)
            if offsets:
                for off in offsets:
                    self.pins.append(Pin(offset + off, True))
            else:
                for i in range(g.num_outputs):
                    self.pins.append(Pin(offset + (i * (1 + g.output_spacing)), True))
        else:
            offsets = getattr(g, 'input_offsets', None)
            if offsets:
                for off in offsets:
                    self.pins.append(Pin(offset + off, False))
            else:
                for i in range(g.num_inputs):
                    self.pins.append(Pin(offset + (i * (1 + g.input_spacing)), False))
                
    def get_next_pin(self, v=None):
        if self.next_free_input_pin >= len(self.pins):
            raise Exception(f"Too many input pins requested from gate for vertex {self.vertex}. Requested {self.next_free_input_pin+1}, but only have {len(self.pins)}")
        self.next_free_input_pin += 1
        return self.pins[self.next_free_input_pin - 1]
        
    def has_next_pin(self):
        return self.next_free_input_pin < len(self.pins)

class MuxPins(GatePins):
    def __init__(self, g, v, offset, top):
        super().__init__(g, v, offset, top)
        
    def get_next_pin(self, v=None):
        return super().get_next_pin(v)

class Net:
    num_nets = 0
    def __init__(self, x_min=float('inf'), x_max=-1):
        self.id = Net.num_nets
        Net.num_nets += 1
        self.track = -1
        self.pins = []
        self.top_pin = None
        self.x_min = x_min
        self.x_max = x_max
        self.outpath = False
        self.out_pin = None
        self.out_partner = None

    def add_pin(self, p, dogleg):
        if p in self.pins: return
        p.set_net(self.id, dogleg)
        self.pins.append(p)
        if p.top:
            if self.top_pin is not None:
                raise Exception(f"Net {self.id} already has an input (top pin) at x={self.top_pin.x}. Cannot add another at x={p.x}")
            self.top_pin = p
        if p.x < self.x_min: self.x_min = p.x
        if p.x > self.x_max: self.x_max = p.x
        
    def has_horizontal_conflict(self, other):
        # A conflict exists if there isn't at least a 1-block gap between the segments.
        return not (self.x_max < other.x_min - 1 or self.x_min > other.x_max + 1)

    def set_out_net(self, out_pin, original):
        self.pins.append(out_pin)
        self.outpath = True
        self.out_pin = out_pin
        self.top_pin = out_pin
        out_pin.set_net(self.id, True)
        
        self.out_partner = original
        original.out_partner = self
        if out_pin in original.pins:
            original.pins.remove(out_pin)
            
    def assign_out_col_x(self, out_col_x):
        self.x_max = out_col_x
        self.x_min = self.out_pin.x
        self.out_partner.x_max = out_col_x
        return out_col_x
        
    def track_z(self):
        return (self.track * 2) + 2

class Node:
    def __init__(self, net_id):
        self.net_id = net_id
        self.routed = False
        self.edges = []

class VCG:
    def __init__(self, pin_pairs, nets):
        self.nodes = {}
        self.num_nets_routed = 0
        self.edges_done = []
        
        for pair in pin_pairs.pairs:
            if not pair.top.is_empty:
                if pair.top.net_id not in self.nodes:
                    self.nodes[pair.top.net_id] = Node(pair.top.net_id)
            if not pair.bot.is_empty:
                if pair.bot.net_id not in self.nodes:
                    self.nodes[pair.bot.net_id] = Node(pair.bot.net_id)
            
            if not pair.top.is_empty and not pair.bot.is_empty and pair.top.net_id != pair.bot.net_id:
                if self.edge_done(pair.top.net_id, pair.bot.net_id): continue
                
                if not self.cycle(self.nodes[pair.top.net_id], pair.bot.net_id):
                    self.nodes[pair.bot.net_id].edges.append(self.nodes[pair.top.net_id])
                    self.edges_done.append((pair.top.net_id, pair.bot.net_id))
                else:
                    out_net = Net()
                    nets[out_net.id] = out_net
                    out_partner = nets[pair.top.net_id]
                    out_net.set_out_net(pair.top, out_partner)
                    
                    x_max = out_net.assign_out_col_x(pin_pairs.add_empty_pair())
                    
                    out_node = Node(out_net.id)
                    self.nodes[out_net.id] = out_node
                    self.nodes[pair.bot.net_id].edges.append(out_node)
                    self.edges_done.append((pair.top.net_id, pair.bot.net_id))

    def get_edge_ids(self, net_id):
        n = self.nodes.get(net_id)
        if not n: return []
        return [e.net_id for e in n.edges]

    def edge_done(self, top, bot):
        return (top, bot) in self.edges_done
        
    def cycle(self, n, cycle_id):
        if n.net_id == cycle_id: return True
        for e in n.edges:
            if self.cycle(e, cycle_id): return True
        return False

    def can_route(self, net_id):
        n = self.nodes.get(net_id)
        if not n or n.routed: return False
        for e in n.edges:
            if not e.routed: return False
        return True

    def routed(self, net_id):
        n = self.nodes[net_id]
        if n.routed: raise Exception("Routed same twice")
        n.routed = True
        self.num_nets_routed += 1

    def done(self):
        return len(self.nodes) == self.num_nets_routed

class Channel:
    def __init__(self, pins_array):
        self.pins_array = pins_array
        self.tracks = []
        self.straight_nets = []

    def find_available_track(self, net, vcg):
        if not net: return
        highest_track = 0
        for vc_id in vcg.get_edge_ids(net.id):
            for track in self.tracks:
                for n in track:
                    if n.id == vc_id and n.track >= highest_track:
                        highest_track = n.track + 1

        for i in range(highest_track, len(self.tracks)):
            has_conflict = False
            for n in self.tracks[i]:
                if n.has_horizontal_conflict(net):
                    has_conflict = True
                    break
            if not has_conflict:
                self.tracks[i].append(net)
                net.track = i
                return

        self.tracks.append([net])
        net.track = len(self.tracks) - 1

    def gen_channel_circuit(self):
        from logic_gates import Circuit
        length = 2 + (len(self.tracks) * 2)
        height = 3
        width = 0

        all_nets = self.straight_nets + [n for track in self.tracks for n in track]
        for n in all_nets:
            if n.x_max > width: width = n.x_max
        width += 1

        circuit = Circuit(width, height, length)
        nets_done = []

        # (x, z) -> net_id for adjacency validation
        occupied_xz = {}
        def check_adjacency(x, z, net_id):
            for dx in [-1, 1]:
                if (x + dx, z) in occupied_xz:
                    other_net = occupied_xz[(x + dx, z)]
                    if other_net != net_id:
                        raise Exception(f"SHORT DETECTED: Net {net_id} and Net {other_net} are adjacent at x={x}/{x+dx}, z={z}.")
            occupied_xz[(x, z)] = net_id

        # Draw Straight Nets first (flat at y=0)
        for n in self.straight_nets:
            for z in range(circuit.size_z):
                check_adjacency(n.x_min, z, n.id)
            self.wire_columns(circuit, n)
            self.repeat_nets(circuit, n)
            nets_done.append(n)

        # Draw Routed Nets (humps through tracks)
        for track in self.tracks:
            for n in track:
                if n in nets_done: continue
                
                z_track = (n.track * 2) + 2
                dog_x = getattr(n, 'dogleg_x', n.x_max)
                
                # Dropped positions validation
                for p in n.pins: check_adjacency(p.x, z_track, n.id)
                if n.outpath or (n.out_partner and not n.outpath):
                    check_adjacency(dog_x, z_track, n.id)
                
                # Vertical columns validation
                for p in n.pins:
                    if p.top:
                        for z in range(0, n.track_z() - 1): check_adjacency(p.x, z, n.id)
                    else:
                        for z in range(n.track_z() + 2, circuit.size_z): check_adjacency(p.x, z, n.id)
                            
                if n.outpath:
                    for z in range(n.track_z() + 2, n.out_partner.track_z() - 1):
                        check_adjacency(dog_x, z, n.id)

                self.place_track(circuit, n.track, n.x_min, n.x_max, n.pins, n)
                nets_done.append(n)

                if n.outpath:
                    circuit.set_block(n.dogleg_x, 0, n.track_z() + 1, "minecraft:repeater[facing=north]")
                if n.out_partner and not n.outpath:
                    circuit.set_block(n.dogleg_x, 0, n.track_z() - 1, "minecraft:repeater[facing=north]")

                self.wire_columns(circuit, n)
                self.repeat_nets(circuit, n)

        # Identify contiguous segments of light_gray_wool at y=1 (sub-bridges)
        light_gray_blocks = [(x, z) for (x, y, z), b in circuit.blocks.items() if y == 1 and b == "minecraft:light_gray_wool"]
        segments_by_z = {} # z -> list of [xmin, xmax]
        for x, z in sorted(light_gray_blocks, key=lambda p: (p[1], p[0])):
            if z not in segments_by_z: segments_by_z[z] = [[x, x]]
            else:
                last = segments_by_z[z][-1]
                if x == last[1] + 1: last[1] = x
                else: segments_by_z[z].append([x, x])

        # Decide which sub-bridge segments to lower
        lowered_segments = set() # (xmin, xmax, z)
        all_segments = set() # (xmin, xmax, z)
        for z, segs in segments_by_z.items():
            for xmin, xmax in segs:
                all_segments.add((xmin, xmax, z))
                if all(not circuit.blocks.get((x, 0, z)) for x in range(xmin, xmax + 1)):
                    lowered_segments.add((xmin, xmax, z))

        # Decide which special blocks (pins/doglegs) to lower
        special_blocks = {(x, z) for (x, y, z), b in circuit.blocks.items() if y == 0 and b in ["minecraft:cyan_wool", "minecraft:pink_wool", "minecraft:yellow_wool"]}
        lowered_specials = set()
        for sx, sz in special_blocks:
            # A special block is lowered if ALL segments touching it are also being lowered
            touching_segments = [s for s in all_segments if s[2] == sz and (s[0] == sx + 1 or s[1] == sx - 1)]
            if touching_segments and all(s in lowered_segments for s in touching_segments):
                lowered_specials.add((sx, sz))

        # Execute lowering for segments
        for xmin, xmax, z in lowered_segments:
            for x in range(xmin, xmax + 1):
                b = circuit.blocks.get((x, 2, z), "minecraft:redstone_wire")
                circuit.set_block(x, 0, z, b)
                if (x, 1, z) in circuit.blocks: del circuit.blocks[(x, 1, z)]
                if (x, 2, z) in circuit.blocks: del circuit.blocks[(x, 2, z)]
        
        # Execute lowering for special blocks
        for sx, sz in lowered_specials:
            b = circuit.blocks.get((sx, 1, sz), "minecraft:redstone_wire")
            circuit.set_block(sx, 0, sz, b)
            if (sx, 1, sz) in circuit.blocks: del circuit.blocks[(sx, 1, sz)]
                
        return circuit

    def place_track(self, channel, track_number, xmin, xmax, pins, n):
        z_track = (track_number * 2) + 2
        z_min = z_track - 1
        
        dogleg_x = getattr(n, 'dogleg_x', xmax)
        actual_xmax = max(xmax, dogleg_x)
        
        top_pin_xs = {p.x for p in pins if p.top}
        bot_pin_xs = {p.x for p in pins if not p.top}
        dogleg_xs = set()
        if n.outpath or (n.out_partner and not n.outpath):
            dogleg_xs.add(dogleg_x)
            
        pin_xs = top_pin_xs | bot_pin_xs | dogleg_xs
        
        bridge_length = actual_xmax - xmin + 1
        bridge_color = "minecraft:red_wool" if bridge_length <= 4 else "minecraft:light_gray_wool"
        
        top_p = next((p for p in pins if p.top), None)
        
        def is_valid_pos(x_pos):
            for xi in [x_pos - 1, x_pos, x_pos + 1]:
                if xi in pin_xs: return False
            return True

        repeater_map = {}
        if top_p:
            limit = 15
            # Right Side
            last_r_x = top_p.x
            while last_r_x + limit <= actual_xmax:
                target_x = last_r_x + limit
                found = False
                for cand_x in range(target_x, last_r_x, -1):
                    if is_valid_pos(cand_x):
                        repeater_map[cand_x] = "west" # retaded minecraft logic: repeater faces the direction it receives input from, not the direction it outputs to. Do not change
                        last_r_x = cand_x
                        found = True
                        break
                if not found: raise Exception(f"Net {self.id}: Cannot place horizontal repeater.")
            # Left Side
            last_r_x = top_p.x
            while last_r_x - limit >= xmin:
                target_x = last_r_x - limit
                found = False
                for cand_x in range(target_x, last_r_x):
                    if is_valid_pos(cand_x):
                        repeater_map[cand_x] = "east" # retaded minecraft logic: repeater faces the direction it receives input from, not the direction it outputs to. Do not change
                        last_r_x = cand_x
                        found = True
                        break
                if not found: raise Exception(f"Net {self.id}: Cannot place horizontal repeater.")

        is_short_bridge = (bridge_length <= 4)
        for x in range(xmin, actual_xmax + 1):
            if is_short_bridge:
                # Flat bridge at ground level (y=0)
                if x in repeater_map:
                    channel.set_block(x, 0, z_track, f"minecraft:repeater[facing={repeater_map[x]}]")
                else:
                    channel.set_block(x, 0, z_track, "minecraft:redstone_wire")
            elif x in top_pin_xs:
                channel.set_block(x, 0, z_track, "minecraft:cyan_wool")
                channel.set_block(x, 1, z_track, "minecraft:redstone_wire")
            elif x in bot_pin_xs:
                channel.set_block(x, 0, z_track, "minecraft:pink_wool")
                channel.set_block(x, 1, z_track, "minecraft:redstone_wire")
            elif x in dogleg_xs:
                channel.set_block(x, 0, z_track, "minecraft:yellow_wool")
                channel.set_block(x, 1, z_track, "minecraft:redstone_wire")
            else:
                channel.set_block(x, 1, z_track, bridge_color)
                if x in repeater_map:
                    channel.set_block(x, 2, z_track, f"minecraft:repeater[facing={repeater_map[x]}]")
                else:
                    channel.set_block(x, 2, z_track, "minecraft:redstone_wire")
            
        for p in pins:
            z_pin = (z_track - 1) if p.top else (z_track + 1)
            channel.set_block(p.x, 0, z_pin, "minecraft:repeater[facing=north]")

    def wire_columns(self, channel, n):
        def set_wire(x, y, z):
            existing = channel.blocks.get((x, y, z))
            if not existing or "redstone_wire" in existing:
                channel.set_block(x, y, z, "minecraft:redstone_wire")

        if n.track == -2:
            for z in range(channel.size_z): set_wire(n.x_min, 0, z)
            return

        for p in n.pins:
            if p.top:
                for z in range(0, n.track_z() - 1): set_wire(p.x, 0, z)
            else:
                for z in range(n.track_z() + 2, channel.size_z): set_wire(p.x, 0, z)
                    
        if n.outpath:
            dog_x = getattr(n, 'dogleg_x', n.x_max)
            for z in range(n.track_z() + 2, n.out_partner.track_z() - 1):
                set_wire(dog_x, 0, z)

    def repeat_nets(self, channel, n):
        if n.track == -2:
             for z in range(14, channel.size_z, 14):
                 channel.set_block(n.x_min, 0, z, "minecraft:repeater[facing=north]")
             return
        for p in n.pins:
            if p.top:
                if n.track_z() > 14:
                    for z in range(n.track_z() - 14, -1, -14):
                        channel.set_block(p.x, 0, z, "minecraft:repeater[facing=north]")
            else:
                if channel.size_z - n.track_z() > 14:
                    for z in range(n.track_z() + 3, channel.size_z, 14):
                        channel.set_block(p.x, 0, z, "minecraft:repeater[facing=north]")
        if n.outpath:
            if n.out_partner.track_z() - n.track_z() > 14:
                for z in range(n.track_z() + 3, n.out_partner.track_z() - 2, 13):
                    channel.set_block(n.x_max, 0, z, "minecraft:repeater[facing=north]")
            
    def size_x(self):
        x_max = 0
        for t in self.tracks:
            for n in t:
                if n.x_max > x_max: x_max = n.x_max
        return x_max
        
    def size_z(self):
        return 2 + (len(self.tracks) * 2)

class Router:
    @staticmethod
    def initialize_pins(top_vertices, top_gates, bottom_vertices, bottom_gates, gate_spacing=1):
        pin_map = {}
        pins_array = PinsArray()
        top_offset = 0
        for i, v in enumerate(top_vertices):
            g = top_gates[i]
            gp = GatePins(g, v, top_offset, True)
            pin_map[v] = gp
            top_offset += g.size_x + gate_spacing
        bottom_offset = 0
        for i, v in enumerate(bottom_vertices):
            g = bottom_gates[i]
            gp = GatePins(g, v, bottom_offset, False)
            pin_map[v] = gp
            bottom_offset += g.size_x + gate_spacing
        for v in top_vertices:
            for p in pin_map[v].pins: pins_array.add_pin(p, True)
        for v in bottom_vertices:
            for p in pin_map[v].pins: pins_array.add_pin(p, False)
        return pin_map, pins_array

    @staticmethod
    def initialize_nets(top_vertices, bottom_vertices, pin_map):
        Net.num_nets = 0
        nets = {}
        for v in top_vertices:
            gate = pin_map[v]
            while gate.has_next_pin():
                next_pin = gate.get_next_pin(v)
                if next_pin.is_empty or next_pin.net_id != -1: continue
                net = Net()
                nets[net.id] = net
                net.add_pin(next_pin, False)
                for next_vertex in v.next:
                    if next_vertex in pin_map:
                        net.add_pin(pin_map[next_vertex].get_next_pin(v), False)
        for v in bottom_vertices:
            gate = pin_map[v]
            while gate.has_next_pin():
                next_pin = gate.get_next_pin(v)
                if next_pin.is_empty or next_pin.net_id != -1: continue
                net = Net()
                nets[net.id] = net
                net.add_pin(next_pin, False)
                for next_vertex in v.next:
                    if next_vertex in pin_map:
                        net.add_pin(pin_map[next_vertex].get_next_pin(v), False)
        return nets

    @staticmethod
    def place_nets(nets, pin_pairs):
        vcg = VCG(pin_pairs, nets)
        all_pin_xs = set()
        for pair in pin_pairs.pairs:
            if not pair.top.is_empty: all_pin_xs.add(pair.top.x)
            if not pair.bot.is_empty: all_pin_xs.add(pair.bot.x)
        for net_id, net in nets.items():
            if net.outpath and not hasattr(net, 'dogleg_x'):
                cand_x = net.x_max + 1
                if cand_x % 2 != 0: cand_x += 1
                while cand_x in all_pin_xs: cand_x += 2
                net.dogleg_x = cand_x
                net.out_partner.dogleg_x = cand_x
                net.x_max = max(net.x_max, net.dogleg_x)
                net.out_partner.x_max = max(net.out_partner.x_max, net.dogleg_x)
        channel = Channel(pin_pairs)
        for net_id, net in list(nets.items()):
            if net.x_min == net.x_max and not net.outpath:
                is_independent = True
                for other_id, node in vcg.nodes.items():
                    if other_id == net_id: continue
                    if net_id in [e.net_id for e in node.edges]:
                        is_independent = False
                        break
                if is_independent and not vcg.nodes[net_id].edges:
                    channel.straight_nets.append(net)
                    net.track = -2
                    vcg.routed(net_id)
        while not vcg.done():
            for pair in pin_pairs.pairs:
                if not pair.top.is_empty and vcg.can_route(pair.top.net_id):
                    channel.find_available_track(nets[pair.top.net_id], vcg)
                    vcg.routed(pair.top.net_id)
                    break
                if not pair.bot.is_empty and vcg.can_route(pair.bot.net_id):
                    channel.find_available_track(nets[pair.bot.net_id], vcg)
                    vcg.routed(pair.bot.net_id)
                    break
        return channel
