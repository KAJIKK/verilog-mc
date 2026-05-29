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
        if p.top: self.top_pin = p
        if p.x < self.x_min: self.x_min = p.x
        if p.x > self.x_max: self.x_max = p.x
        
    def has_horizontal_conflict(self, other):
        return not (self.x_max < other.x_min or self.x_min > other.x_max)

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
        return 2 if self.track == 0 else (self.track * 3) + 2

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
                    out_partner = nets[pair.top.net_id]
                    out_net.set_out_net(pair.top, out_partner)
                    
                    x_max = out_net.assign_out_col_x(pin_pairs.add_empty_pair())
                    out_partner.x_max = x_max
                    nets[out_net.id] = out_net
                    
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
        length = 2 + (3 * len(self.tracks))
        height = 3
        width = 0
        
        all_nets = self.straight_nets + [n for track in self.tracks for n in track]
        for n in all_nets:
            if n.x_max > width: width = n.x_max
        width += 1
        
        circuit = Circuit(width, height, length)
        nets_done = []
        
        # Draw Straight Nets first (flat at y=0)
        for n in self.straight_nets:
            self.wire_columns(circuit, n)
            self.repeat_nets(circuit, n)
            nets_done.append(n)

        # Draw Routed Nets (humps through tracks)
        for track in self.tracks:
            for n in track:
                if n in nets_done: continue
                self.place_track(circuit, n.track, n.x_min, n.x_max, n.pins)
                nets_done.append(n)
                
                # Color code outpaths (doglegs) as YELLOW
                if n.outpath:
                    circuit.set_block(n.x_max, 0, n.track_z() + 1, "minecraft:yellow_wool")
                    circuit.set_block(n.x_max, 1, n.track_z() + 1, "minecraft:redstone_wire")
                if n.out_partner and not n.outpath:
                    circuit.set_block(n.x_max, 0, n.track_z() - 1, "minecraft:yellow_wool")
                    circuit.set_block(n.x_max, 1, n.track_z() - 1, "minecraft:redstone_wire")
                    
                self.wire_columns(circuit, n)
                self.repeat_nets(circuit, n)
                
        return circuit

    def place_track(self, channel, track_number, xmin, xmax, pins):
        z_min = 1 + (3 * track_number)
        z_track = z_min + 1
        
        # Color code horizontal tracks as LIGHT GRAY
        for x in range(xmin, xmax + 1):
            channel.set_block(x, 1, z_track, "minecraft:light_gray_wool")
            channel.set_block(x, 2, z_track, "minecraft:redstone_wire")
            
        for p in pins:
            if p.top:
                # Color code top pin entries (gate outputs) as CYAN
                channel.set_block(p.x, 0, z_min, "minecraft:cyan_wool")
                channel.set_block(p.x, 1, z_min, "minecraft:redstone_wire")
            else:
                # Color code bottom pin entries (gate inputs) as PINK
                channel.set_block(p.x, 0, z_track + 1, "minecraft:pink_wool")
                channel.set_block(p.x, 1, z_track + 1, "minecraft:redstone_wire")

    def wire_columns(self, channel, n):
        if n.track == -2: # Straight optimization
            for z in range(channel.size_z):
                channel.set_block(n.x_min, 0, z, "minecraft:redstone_wire")
            return

        for p in n.pins:
            if p.top:
                for z in range(0, n.track_z() - 1):
                    channel.set_block(p.x, 0, z, "minecraft:redstone_wire")
            else:
                for z in range(n.track_z() + 2, channel.size_z):
                    channel.set_block(p.x, 0, z, "minecraft:redstone_wire")
                    
        if n.outpath:
            for z in range(n.track_z() + 2, n.out_partner.track_z() - 1):
                channel.set_block(n.x_max, 0, z, "minecraft:redstone_wire")

    def repeat_nets(self, channel, n):
        if n.track == -2: # Straight optimization
             for z in range(14, channel.size_z, 14):
                 channel.set_block(n.x_min, 0, z, "minecraft:repeater[facing=north]")
             return

        for p in n.pins:
            if p.top:
                if n.track_z() > 14:
                    for z in range(n.track_z() - 14, -1, -14):
                        channel.set_block(p.x, 0, z, "minecraft:repeater[facing=north]")
                if p.x > n.x_min:
                    channel.set_block(p.x - 1, 2, n.track_z(), "minecraft:repeater[facing=east]")
                if p.x < n.x_max:
                    channel.set_block(p.x + 1, 2, n.track_z(), "minecraft:repeater[facing=west]")
            else:
                if channel.size_z - n.track_z() > 14:
                    for z in range(n.track_z() + 3, channel.size_z, 14):
                        channel.set_block(p.x, 0, z, "minecraft:repeater[facing=north]")
                if not (not n.outpath and n.out_partner):
                    if p.x > n.x_min:
                        if p.x > n.top_pin.x:
                            channel.set_block(p.x - 1, 2, n.track_z(), "minecraft:repeater[facing=west]")
                    if p.x < n.x_max:
                        if p.x < n.top_pin.x:
                            channel.set_block(p.x + 1, 2, n.track_z(), "minecraft:repeater[facing=east]")
                else:
                    channel.set_block(p.x + 1, 2, n.track_z(), "minecraft:repeater[facing=east]")

        if n.x_max - n.x_min > 19:
            for x in range(n.x_min + 2, n.x_max - 2, 14):
                if any(x == p.x for p in n.pins): x -= 1
                if not (not n.outpath and n.out_partner):
                    if x < n.top_pin.x:
                        channel.set_block(x, 2, n.track_z(), "minecraft:repeater[facing=east]")
                    if x > n.top_pin.x:
                        channel.set_block(x, 2, n.track_z(), "minecraft:repeater[facing=west]")
                else:
                    channel.set_block(x, 2, n.track_z(), "minecraft:repeater[facing=east]")

        if n.outpath:
            if n.out_partner.track_z() - n.track_z() > 14:
                for z in range(n.track_z() + 3, n.out_partner.track_z() - 2, 13):
                    channel.set_block(n.x_max, 0, z, "minecraft:repeater[facing=north]")
            channel.set_block(n.x_max - 1, 2, n.track_z(), "minecraft:repeater[facing=west]")
            
        if not n.outpath and n.out_partner:
            channel.set_block(n.x_max - 1, 2, n.track_z(), "minecraft:repeater[facing=east]")
            
    def size_x(self):
        x_max = 0
        for t in self.tracks:
            for n in t:
                if n.x_max > x_max: x_max = n.x_max
        return x_max
        
    def size_z(self):
        return 2 + (len(self.tracks) * 3)

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
            if v.name == '$abc$108$auto$blifparse.cc:397:parse_blif$110':
                print(f"DEBUG {v.name}: g.num_inputs={g.num_inputs}, len(gp.pins)={len(gp.pins)}")
            pin_map[v] = gp
            bottom_offset += g.size_x + gate_spacing
            
        for v in top_vertices:
            for p in pin_map[v].pins:
                pins_array.add_pin(p, True)
                
        for v in bottom_vertices:
            for p in pin_map[v].pins:
                pins_array.add_pin(p, False)
                
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
        channel = Channel(pin_pairs)
        
        # Step 1: Detect Straight Nets (Single column, no vertical constraints)
        for net_id, net in list(nets.items()):
            if net.x_min == net.x_max and not net.outpath:
                # If it's a single-column net, check if it's involved in any VCG constraints
                # (i.e., no other net is above or below it in this column)
                is_independent = True
                for other_id, node in vcg.nodes.items():
                    if other_id == net_id: continue
                    if net_id in [e.net_id for e in node.edges]:
                        is_independent = False
                        break
                
                if is_independent and not vcg.nodes[net_id].edges:
                    channel.straight_nets.append(net)
                    net.track = -2 # Special marker for straight wires
                    vcg.routed(net_id)
        
        # Step 2: Route the remaining nets using tracks
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
