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
        for i in range(len(self.vertex_layers) - 1):
            top_vertices = self.vertex_layers[i]
            top_gates = self.gate_layers[i]
            bottom_vertices = self.vertex_layers[i+1]
            bottom_gates = self.gate_layers[i+1]
            
            pin_map, pins_array = Router.initialize_pins(top_vertices, top_gates, bottom_vertices, bottom_gates, 1)
            nets = Router.initialize_nets(top_vertices, bottom_vertices, pin_map)
            channel = Router.place_nets(nets, pins_array)
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

    def gen_circuit(self):
        size_x = 0
        size_y = 0
        size_z = 0
        
        layers_size_z = []
        for layer in self.gate_layers:
            this_size_x = len(layer) - 1 if layer else 0
            this_size_y = 0
            this_size_z = 0
            for c in layer:
                this_size_x += c.size_x
                if c.size_y > this_size_y: this_size_y = c.size_y
                if c.size_z > this_size_z: this_size_z = c.size_z
                
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
            x_offset = 0
            for g in self.gate_layers[i]:
                # insert circuit
                for (lx, ly, lz), b in g.blocks.items():
                    circuit.set_block(x_offset + lx, 0 + ly, z_offset + lz, b)
                    
                if g.size_z - 1 < layers_size_z[i]:
                    for z in range(g.size_z, layers_size_z[i]):
                        if z == layers_size_z[i] - 1:
                            circuit.set_block(x_offset, 0, z_offset + z, "minecraft:repeater[facing=north]")
                        else:
                            circuit.set_block(x_offset, 0, z_offset + z, "minecraft:redstone_wire")
                            
                x_offset += 1 + g.size_x
            z_offset += layers_size_z[i]
            
            if i < len(self.gate_layers) - 1:
                c = self.channels[i]
                c_circuit = c.gen_channel_circuit()
                for (cx, cy, cz), b in c_circuit.blocks.items():
                    circuit.set_block(cx, cy, z_offset + cz, b)
                z_offset += c.size_z()
                
        return circuit
