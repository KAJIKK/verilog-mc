from netlist_parser import VertexType, Vertex, Graph
from router import Router
from logic_gates import LogicGates, Circuit

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

            # Now perform routing with the optimized offsets
            pin_map, pins_array = Router.initialize_pins(self.vertex_layers[i], self.gate_layers[i], 
                                                        self.vertex_layers[i+1], self.gate_layers[i+1], 1)
            nets = Router.initialize_nets(self.vertex_layers[i], self.vertex_layers[i+1], pin_map)
            
            # Update signs with Net IDs for debugging
            for net in nets.values():
                for p in net.pins:
                    # Look for input/output gates and update their signs
                    # We find which vertex this pin belongs to
                    v_found = None
                    for v, gp in pin_map.items():
                        if p in gp.pins:
                            v_found = v
                            break
                    
                    if v_found:
                        idx = -1
                        is_top = False
                        if v_found in self.vertex_layers[i]:
                            idx = self.vertex_layers[i].index(v_found)
                            is_top = True
                        elif v_found in self.vertex_layers[i+1]:
                            idx = self.vertex_layers[i+1].index(v_found)
                            is_top = False
                        
                        if idx != -1:
                            layer = self.gate_layers[i] if is_top else self.gate_layers[i+1]
                            g = layer[idx]
                            if g.is_io:
                                # Re-generate the gate with the net_id
                                if v_found.type == VertexType.INPUT:
                                    new_g = LogicGates.input_gate(v_found.name, net.id)
                                else:
                                    new_g = LogicGates.output_gate(v_found.name, net.id)
                                new_g.x_offset = g.x_offset
                                layer[idx] = new_g

            channel = Router.place_nets(nets, pins_array, self.gate_layers[i], self.gate_layers[i+1], 1)
            self.channels.append(channel)

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
        import xml.etree.ElementTree as ET

        # Scaling factors
        SCALE = 10
        LAYER_GAP = 5
        
        # Calculate total dimensions
        total_width = 0
        total_height = 0
        
        layer_info = []
        for i, layer in enumerate(self.gate_layers):
            l_width = 0
            l_height = 0
            for g in layer:
                w = g.x_offset + g.size_x
                if w > l_width: l_width = w
                if g.size_z > l_height: l_height = g.size_z
            
            chan_h = self.channels[i].size_z() if i < len(self.channels) else 0
            layer_info.append({'w': l_width, 'h': l_height, 'ch': chan_h})
            
            if l_width > total_width: total_width = l_width
            total_height += l_height + chan_h
            
        # Create SVG root
        svg = ET.Element('svg', {
            'xmlns': 'http://www.w3.org/2000/svg',
            'width': str(total_width * SCALE),
            'height': str(total_height * SCALE),
            'viewBox': f"0 0 {total_width * SCALE} {total_height * SCALE}",
            'style': 'background-color: #1e1e1e'
        })
        
        # Define styles
        style = ET.SubElement(svg, 'style')
        style.text = """
            .gate { fill: #333; stroke: #555; stroke-width: 0.5; }
            .net { fill: none; stroke-width: 0.8; opacity: 0.7; }
            .pin { r: 1.5; }
            .text { font-family: sans-serif; font-size: 3px; fill: white; }
            .net-label { font-size: 2px; }
        """
        
        colors = ["#ff5555", "#55ff55", "#5555ff", "#ffff55", "#ff55ff", "#55ffff", "#ffb86c", "#bd93f9"]
        
        current_z = 0
        for i, layer in enumerate(self.gate_layers):
            info = layer_info[i]
            
            # Draw Gates
            for idx, g in enumerate(layer):
                v = self.vertex_layers[i][idx]
                rect = ET.SubElement(svg, 'rect', {
                    'x': str(g.x_offset * SCALE),
                    'y': str(current_z * SCALE),
                    'width': str(g.size_x * SCALE),
                    'height': str(g.size_z * SCALE),
                    'class': 'gate'
                })
                
                # Label gate
                name = getattr(v, 'name', 'relay')
                if len(name) > 10: name = name[:8] + '..'
                text = ET.SubElement(svg, 'text', {
                    'x': str(g.x_offset * SCALE + 2),
                    'y': str(current_z * SCALE + 5),
                    'class': 'text'
                })
                text.text = f"{name} ({getattr(v, 'func_type', 'RELAY')})"

            current_z += info['h']
            
            # Draw Channel Routing
            if i < len(self.channels):
                chan = self.channels[i]
                all_nets = chan.straight_nets + [n for t in chan.tracks for n in t]
                
                for net in all_nets:
                    color = colors[net.id % len(colors)]
                    
                    # Vertical from top pins to track
                    for p in net.pins:
                        if p.top:
                            z_start = current_z - 0.5
                            z_end = current_z + (net.track_z() / SCALE if net.track >= 0 else chan.size_z())
                            ET.SubElement(svg, 'line', {
                                'x1': str(p.x * SCALE + SCALE/2),
                                'y1': str(z_start * SCALE),
                                'x2': str(p.x * SCALE + SCALE/2),
                                'y2': str(z_end * SCALE),
                                'stroke': color,
                                'class': 'net'
                            })

                    # Horizontal Track
                    if net.track >= 0:
                        tz = current_z + (net.track_z() / 1.0)
                        ET.SubElement(svg, 'line', {
                            'x1': str(net.x_min * SCALE + SCALE/2),
                            'y1': str(tz * SCALE),
                            'x2': str(net.x_max * SCALE + SCALE/2),
                            'y2': str(tz * SCALE),
                            'stroke': color,
                            'class': 'net'
                        })
                        # Net ID Label
                        t = ET.SubElement(svg, 'text', {
                            'x': str(net.x_min * SCALE),
                            'y': str(tz * SCALE - 1),
                            'fill': color,
                            'style': 'font-size: 4px'
                        })
                        t.text = f"N{net.id}"

                    # Vertical to bottom pins
                    for p in net.pins:
                        if not p.top:
                            z_start = current_z + (net.track_z() / 1.0 if net.track >= 0 else 0)
                            z_end = current_z + info['ch']
                            ET.SubElement(svg, 'line', {
                                'x1': str(p.x * SCALE + SCALE/2),
                                'y1': str(z_start * SCALE),
                                'x2': str(p.x * SCALE + SCALE/2),
                                'y2': str(z_end * SCALE),
                                'stroke': color,
                                'class': 'net'
                            })
                            
                current_z += info['ch']

        # Save to file
        tree = ET.ElementTree(svg)
        tree.write(filename)
        print(f"Debug SVG saved to {filename}")

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
            size_z += c.size_z() + 1
            
        circuit = Circuit(size_x, size_y, size_z)
        
        z_offset = 0
        for i in range(len(self.gate_layers)):
            for g in self.gate_layers[i]:
                # insert circuit
                for (lx, ly, lz), b in g.blocks.items():
                    circuit.set_block(g.x_offset + lx, 0 + ly, z_offset + lz, b)
                    
                if g.size_z - 1 < layers_size_z[i]:
                    for z in range(g.size_z, layers_size_z[i]):
                        # Place a repeater every 14 blocks or at the very end
                        dist_from_gate = z - g.size_z + 1
                        if z == layers_size_z[i] - 1 or dist_from_gate % 14 == 0:
                            circuit.set_block(g.x_offset, 0, z_offset + z, "minecraft:repeater[facing=north]")
                        else:
                            circuit.set_block(g.x_offset, 0, z_offset + z, "minecraft:redstone_wire")
                            
            z_offset += layers_size_z[i]
            
            if i < len(self.gate_layers) - 1:
                c = self.channels[i]
                c_circuit = c.gen_channel_circuit()
                for (cx, cy, cz), b in c_circuit.blocks.items():
                    circuit.set_block(cx, cy, z_offset + cz, b)
                z_offset += c.size_z()
                
        return circuit
