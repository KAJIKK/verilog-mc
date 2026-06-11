from netlist_parser import VertexType, Vertex, Graph
from router import route as route_new
from logic_gates import LogicGates, Circuit

class ChannelWrapper:
    def __init__(self, circuit):
        self.circuit = circuit
        self.straight_nets = [] # For SVG compatibility (empty for now)
        self.tracks = []
        
    def gen_channel_circuit(self):
        return self.circuit
        
    def size_z(self):
        return self.circuit.size_z
        
    def size_x(self):
        return self.circuit.size_x

class IntermediateCircuit:
    def __init__(self):
        self.vertex_layers = []
        self.gate_layers = []
        self.channels = []

    def load_graph(self, graph):
        finished = set()
        in_process = []
        
        for v in graph.vertices.values():
            if v.type == VertexType.INPUT or getattr(v, 'func_type', '') in ["HIGH", "LOW"]:
                in_process.append(v)
                
        layer_num = 0
        while in_process:
            self.vertex_layers.append([])
            process_done = []
            to_process = []
            
            for v in in_process:
                valid = True
                for p in v.before:
                    if p not in finished:
                        valid = False
                        break
                
                if valid:
                    self.vertex_layers[layer_num].append(v)
                    process_done.append(v)
                    for n in v.next:
                        to_process.append(n)
                        
            for v in process_done:
                in_process.remove(v)
                finished.add(v)
                
            for v in to_process:
                if v not in in_process:
                    in_process.append(v)
                    
            layer_num += 1
            
        outputs_not_in_last = []
        for i in range(len(self.vertex_layers) - 1):
            v_l = self.vertex_layers[i]
            to_remove = []
            for v in v_l:
                if v.type == VertexType.OUTPUT:
                    outputs_not_in_last.append(v)
                    to_remove.append(v)
            for v in to_remove:
                v_l.remove(v)
                
        last_layer = self.vertex_layers[-1]
        for v in outputs_not_in_last:
            last_layer.append(v)
            
        relay_count = 0
        for i in range(len(self.vertex_layers) - 1):
            layer = self.vertex_layers[i]
            next_layer = self.vertex_layers[i+1]
            
            for v in layer:
                add_to_next = []
                remove_from_next = []
                
                for next_v in v.next:
                    if next_v not in next_layer:
                        relay = Vertex(f"relay_{relay_count}", VertexType.FUNCTION, func_type="RELAY")
                        relay_count += 1
                        next_layer.append(relay)
                        
                        remove_from_next.append(next_v)
                        next_v.before.remove(v)
                        
                        add_to_next.append(relay)
                        relay.add_before(v)
                        
                        relay.add_next(next_v)
                        next_v.add_before(relay)
                        
                for x in add_to_next:
                    v.add_next(x)
                for x in remove_from_next:
                    if x in v.next:
                        v.next.remove(x)

    def print_layers(self):
        for i, layer in enumerate(self.vertex_layers):
            print(f"Layer {i}:")
            for v in layer:
                print(f"  {v}")

    def build_gates(self):
        for layer in self.vertex_layers:
            gate_layer = []
            for v in layer:
                gate_layer.append(self.gen_gate(v))
            self.gate_layers.append(gate_layer)

    def gen_gate(self, v):
        ftype = getattr(v, 'func_type', '')
        if v.type == VertexType.INPUT:
            return LogicGates.input_gate(v.name)
        elif v.type == VertexType.OUTPUT:
            return LogicGates.output_gate(v.name)
        elif ftype == 'RELAY':
            return LogicGates.relay()
        elif ftype in ['AND', 'AND2', '$_AND_']:
            inputs = getattr(v, 'num_inputs', max(1, len(v.before)))
            return LogicGates.and_gate(inputs)
        elif ftype in ['NAND', 'NAND2', '$_NAND_']:
            inputs = getattr(v, 'num_inputs', max(1, len(v.before)))
            return LogicGates.nand_gate(inputs)
        elif ftype in ['OR', 'OR2', '$_OR_']:
            inputs = getattr(v, 'num_inputs', max(1, len(v.before)))
            return LogicGates.or_gate(inputs)
        elif ftype in ['NOR', 'NOR2', '$_NOR_']:
            inputs = getattr(v, 'num_inputs', max(1, len(v.before)))
            return LogicGates.nor_gate(inputs)
        elif ftype in ['XOR', 'XOR2', '$_XOR_', 'XNOR', 'XNOR2', '$_XNOR_']:
            return LogicGates.xor_gate()
        elif ftype in ['INV', 'NOT', 'NOT1', '$_NOT_']:
            return LogicGates._not()
        elif ftype in ['MUX', '$_MUX_']:
            return LogicGates.mux_gate()
        else:
            print(f"WARNING: Unknown gate type '{ftype}' for vertex {v.name}. Falling back to RELAY.")
            return LogicGates.relay()

    def _get_pins(self, v, g, is_top):
        pins = []
        offset = g.x_offset
        if is_top:
            offsets = getattr(g, 'output_offsets', None)
            if offsets:
                for off in offsets: pins.append(offset + off)
            else:
                num_outputs = getattr(g, 'num_outputs', 1)
                for idx in range(num_outputs):
                    pins.append(offset + (idx * (1 + getattr(g, 'output_spacing', 1))))
        else:
            offsets = getattr(g, 'input_offsets', None)
            if offsets:
                for off in offsets: pins.append(offset + off)
            else:
                num_inputs = getattr(g, 'num_inputs', 1)
                for idx in range(num_inputs):
                    pins.append(offset + (idx * (1 + getattr(g, 'input_spacing', 1))))
        return pins

    def route_channels(self):
        # Initial gate positions for the first layer
        gate_centers = {} # vertex -> x_center
        curr_x = 0
        for i, v in enumerate(self.vertex_layers[0]):
            g = self.gate_layers[0][i]
            g.x_offset = curr_x
            gate_centers[v] = curr_x + (g.size_x / 2)
            curr_x += g.size_x + 1

        for i in range(len(self.vertex_layers) - 1):
            top_vertices = self.vertex_layers[i]
            top_gates = self.gate_layers[i]
            bottom_vertices = self.vertex_layers[i+1]
            bottom_gates = self.gate_layers[i+1]
            
            # Sort bottom_vertices based on the average X-position of their inputs
            def get_target_x(v):
                inputs = [inp for inp in v.before if inp in gate_centers]
                if not inputs: return float('inf') 
                return sum(gate_centers[inp] for inp in inputs) / len(inputs)

            combined = list(zip(bottom_vertices, bottom_gates))
            combined.sort(key=lambda pair: get_target_x(pair[0]))
            
            # Update the layers with sorted versions
            self.vertex_layers[i+1] = [p[0] for p in combined]
            self.gate_layers[i+1] = [p[1] for p in combined]
            
            # Calculate optimized offsets with gaps for the next layer
            new_gate_centers = {}
            curr_x = 0
            for v, g in combined:
                t_x = get_target_x(v)
                if t_x == float('inf'):
                    start_x = curr_x
                else:
                    # Align center of gate with t_x, but don't overlap with curr_x
                    start_x = max(curr_x, int(t_x - g.size_x / 2))
                
                # Force even start_x to keep pins on even coordinates and avoid shorts
                if start_x % 2 != 0: start_x += 1
                
                g.x_offset = start_x
                new_gate_centers[v] = start_x + (g.size_x / 2)
                curr_x = start_x + g.size_x + 1
            gate_centers = new_gate_centers

            # NEW ROUTING LOGIC using router_new.py
            nets_input = []
            vertex_pin_counters = {} 
            
            for v_idx, v in enumerate(top_vertices):
                g = top_gates[v_idx]
                out_xs = self._get_pins(v, g, True)
                
                bits = getattr(v, 'bits', [])
                net_id = bits[0] if bits and isinstance(bits[0], int) else -1
                
                for ox in out_xs:
                    pin_list = [(ox, 0, True)]
                    # Connect to next layer
                    for vn in v.next:
                        if vn in bottom_vertices:
                            vn_idx = bottom_vertices.index(vn)
                            gn = bottom_gates[vn_idx]
                            in_xs = self._get_pins(vn, gn, False)
                            p_idx = vertex_pin_counters.get(vn, 0)
                            if p_idx < len(in_xs):
                                pin_list.append((in_xs[p_idx], 0, False))
                                vertex_pin_counters[vn] = p_idx + 1
                    
                    if len(pin_list) > 1 or (len(pin_list) == 1 and pin_list[0][2]):
                        nets_input.append(pin_list)
                        
                        # Update signs for IO gates
                        if g.is_io and net_id != -1:
                            # Re-generate the gate with the net_id (using index + 1 as placeholder or net_id)
                            # Using index in nets_input + 1 for now to match router_new labeling
                            if v.type == VertexType.INPUT:
                                new_g = LogicGates.input_gate(v.name, net_id)
                            else:
                                new_g = LogicGates.output_gate(v.name, net_id)
                            new_g.x_offset = g.x_offset
                            top_gates[v_idx] = new_g

            # Also check if any bottom gates are IO and need sign updates
            for v_idx, v in enumerate(bottom_vertices):
                g = bottom_gates[v_idx]
                if g.is_io:
                    bits = getattr(v, 'bits', [])
                    net_id = bits[0] if bits and isinstance(bits[0], int) else -1
                    if net_id != -1:
                        if v.type == VertexType.INPUT:
                            new_g = LogicGates.input_gate(v.name, net_id)
                        else:
                            new_g = LogicGates.output_gate(v.name, net_id)
                        new_g.x_offset = g.x_offset
                        bottom_gates[v_idx] = new_g

            # Perform routing
            channel_circuit = route_new(nets_input, top_gates, bottom_gates)
            self.channels.append(ChannelWrapper(channel_circuit))

    def get_statistics(self):
        stats = {
            "gate_counts": {},
            "total_gates": 0,
            "max_delay": len(self.vertex_layers)
        }
        
        for layer in self.vertex_layers:
            for v in layer:
                ftype = getattr(v, 'func_type', v.type)
                stats["gate_counts"][ftype] = stats["gate_counts"].get(ftype, 0) + 1
                stats["total_gates"] += 1
                
        return stats

    def save_debug_svg(self, filename):
        print("WARNING: save_debug_svg is currently disabled for the new router.")
        pass

    def gen_circuit(self):
        size_x = 0
        size_y = 0
        size_z = 0
        
        layers_size_z = []
        for i, layer in enumerate(self.gate_layers):
            this_size_x = 0
            this_size_y = 0
            this_size_z = 0
            for g in layer:
                right_edge = g.x_offset + g.size_x
                if right_edge > this_size_x: this_size_x = right_edge
                if g.size_y > this_size_y: this_size_y = g.size_y
                if g.size_z > this_size_z: this_size_z = g.size_z
                
            if this_size_x > size_x: size_x = this_size_x
            if this_size_y > size_y: size_y = this_size_y
            size_z += this_size_z
            layers_size_z.append(this_size_z)
            
        if size_y < 3: size_y = 3
        
        for c in self.channels:
            if c.size_x() + 1 > size_x: size_x = c.size_x() + 1
            size_z += c.size_z()
            
        circuit = Circuit(size_x, size_y, size_z)
        sources = [] # (pos, power, direction)
        gate_repeaters = set() # (x, y, z)
        
        z_offset = 0
        for i in range(len(self.gate_layers)):
            for j, g in enumerate(self.gate_layers[i]):
                v = self.vertex_layers[i][j]
                # Insert gate blocks
                for (lx, ly, lz), b in g.blocks.items():
                    px, py, pz = g.x_offset + lx, 0 + ly, z_offset + lz
                    circuit.set_block(px, py, pz, b)
                    if "repeater" in b:
                        gate_repeaters.add((px, py, pz))

                # If this gate is a source of power (not an output, not a relay bridge)
                # find its output point to start tracking wire runs
                ftype = getattr(v, 'func_type', '')
                if v.type == VertexType.INPUT or (v.type == VertexType.FUNCTION and ftype != 'RELAY'):
                    # Source point is at the end of the gate's output pin
                    out_offsets = getattr(g, 'output_offsets', None) or [0]
                    # We assume north-facing gates (output is at z = g.size_z - 1)
                    # We track the first block of the subsequent wire as the source
                    source_x = g.x_offset + out_offsets[0]
                    source_z = z_offset + g.size_z
                    sources.append(((source_x, 0, source_z), 15, "south"))

                # Extend wire through the layer gap (padding)
                if g.size_z < layers_size_z[i]:
                    out_offsets = getattr(g, 'output_offsets', None) or [0]
                    wire_x = g.x_offset + out_offsets[0]
                    for z in range(g.size_z, layers_size_z[i]):
                        circuit.set_block(wire_x, 0, z_offset + z, "minecraft:redstone_wire")
                            
            z_offset += layers_size_z[i]
            
            if i < len(self.gate_layers) - 1:
                c = self.channels[i]
                c_circuit = c.gen_channel_circuit()
                for (cx, cy, cz), b in c_circuit.blocks.items():
                    circuit.set_block(cx, cy, z_offset + cz, b)
                z_offset += c.size_z()
                
        return circuit, sources, gate_repeaters
