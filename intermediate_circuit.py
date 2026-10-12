from netlist_parser import VertexType, Vertex, Graph
from router import route as route_new
from logic_gates import LogicGates, Circuit

def parallel_route_worker(nets_in, tgl, bgl, ncx, channel_idx, pin_headroom=()):
    from time import perf_counter
    started = perf_counter()
    if nets_in:
        from router import route as route_new
        circuit = route_new(nets_in, min_width=max(1,ncx), pin_headroom=pin_headroom)
    else:
        circuit = Circuit(ncx, 3, 1)
        circuit.route_stats = {'attempts': 0}
    circuit.route_stats['seconds'] = perf_counter() - started
    return circuit

class ChannelWrapper:
    def __init__(self, circuit):
        self.circuit = circuit
        self.straight_nets = [] 
        self.tracks = []
    def gen_channel_circuit(self): return self.circuit
    def size_z(self): return self.circuit.size_z
    def size_x(self): return self.circuit.size_x

class IntermediateCircuit:
    def __init__(self):
        self.vertex_layers = []
        self.gate_layers = []
        self.channels = []

    def load_graph(self, graph):
        vertices = list(graph.vertices.values())
        placed = set()
        self.v_to_layer = {}
        
        while len(placed) < len(vertices):
            candidates = [v for v in vertices if v not in placed]
            ready = [v for v in candidates if all(p in placed for p in v.before)]
            if not ready:
                candidates.sort(key=lambda v: (v.type != VertexType.OUTPUT, len([p for p in v.before if p in placed]), -len(v.before)), reverse=True)
                ready = [candidates[0]]
                print(f"Cycle detected! Breaking at vertex: {ready[0].name}")
            for v in ready:
                placed.add(v)
                self.v_to_layer[v] = len(self.vertex_layers)
            self.vertex_layers.append(ready)

        # Force OUTPUT to last layer
        last_idx = len(self.vertex_layers) - 1
        for i in range(last_idx):
            outs = [v for v in self.vertex_layers[i] if v.type == VertexType.OUTPUT]
            for v in outs:
                self.vertex_layers[i].remove(v)
                self.vertex_layers[last_idx].append(v)
                self.v_to_layer[v] = last_idx

        # Optimize layers with only 1 real gate by pushing them to adjacent layers
        for i in range(1, len(self.vertex_layers) - 1):
            layer = self.vertex_layers[i]
            if len(layer) == 1:
                v = layer[0]
                if v.type not in [VertexType.INPUT, VertexType.OUTPUT]:
                    target_layer_idx = i - 1
                    if target_layer_idx == 0:
                        target_layer_idx = i + 1
                    if target_layer_idx < len(self.vertex_layers) - 1:
                        print(f"Optimization: Pushing single real gate {v.name} from layer {i} to layer {target_layer_idx}")
                        self.vertex_layers[target_layer_idx].append(v)
                        self.v_to_layer[v] = target_layer_idx
                        self.vertex_layers[i] = []

        # Remove empty layers and adjust layer indices
        new_vertex_layers = []
        for idx, layer in enumerate(self.vertex_layers):
            if idx == 0 or idx == len(self.vertex_layers) - 1 or len(layer) > 0:
                new_vertex_layers.append(layer)
        
        self.vertex_layers = new_vertex_layers
        self.v_to_layer = {}
        for l_idx, layer in enumerate(self.vertex_layers):
            for v in layer:
                self.v_to_layer[v] = l_idx

        relay_count = 0
        for u in vertices:
            ul = self.v_to_layer[u]
            if len(getattr(u, 'output_bits', {})) > 1:
                # Separate relay chains prevent complementary outputs from
                # being shorted together when crossing intermediate layers.
                for v in list(u.next):
                    vl = self.v_to_layer[v]
                    if vl == ul + 1:
                        continue
                    wanted = (v.bits if v.type == VertexType.OUTPUT else
                              [bit for bits in getattr(v, 'input_bits', {}).values() for bit in bits])
                    bits = [bit for bit in u.bits if bit in wanted]
                    step = 1 if vl > ul else -1
                    layers = range(ul + 1, vl, step) if step == 1 else range(ul, vl - 1, step)
                    for bit in bits:
                        prev = u
                        for r_layer in layers:
                            relay = Vertex(f'relay_signal_{relay_count}', VertexType.FUNCTION,
                                           func_type='RELAY', bits=[bit])
                            relay_count += 1
                            self.vertex_layers[r_layer].append(relay)
                            self.v_to_layer[relay] = r_layer
                            prev.add_next(relay)
                            relay.add_before(prev)
                            prev = relay
                        prev.add_next(v)
                        v.add_before(prev)
                    u.next.remove(v)
                    v.before.remove(u)
                continue
            forward_dests = []
            backward_dests = []
            
            for v in list(u.next):
                vl = self.v_to_layer[v]
                if vl <= ul:
                    backward_dests.append(v)
                elif vl > ul + 1:
                    forward_dests.append(v)
            
            # 1. Process backward/same-layer edges (processed individually as before)
            for v in backward_dests:
                vl = self.v_to_layer[v]
                prev = u
                for r_layer in range(ul, vl - 1, -1):
                    relay = Vertex(f"relay_backward_{relay_count}", VertexType.FUNCTION, func_type="RELAY", bits=getattr(u, 'bits', []))
                    relay_count += 1
                    self.vertex_layers[r_layer].append(relay)
                    self.v_to_layer[relay] = r_layer
                    
                    prev.add_next(relay)
                    relay.add_before(prev)
                    prev = relay
                
                prev.add_next(v)
                v.add_before(prev)
                u.next.remove(v)
                v.before.remove(u)
            
            # 2. Process forward edges (shared relays for all forward destinations from u)
            if forward_dests:
                max_vl = max(self.v_to_layer[v] for v in forward_dests)
                relays = {}
                prev = u
                for r_layer in range(ul + 1, max_vl):
                    relay = Vertex(f"relay_forward_{relay_count}", VertexType.FUNCTION, func_type="RELAY", bits=getattr(u, 'bits', []))
                    relay_count += 1
                    self.vertex_layers[r_layer].append(relay)
                    self.v_to_layer[relay] = r_layer
                    
                    prev.add_next(relay)
                    relay.add_before(prev)
                    
                    relays[r_layer] = relay
                    prev = relay
                
                # Redirect destinations to use the appropriate relay in the shared chain
                for v in forward_dests:
                    vl = self.v_to_layer[v]
                    source_relay = relays[vl - 1]
                    source_relay.add_next(v)
                    v.add_before(source_relay)
                    
                    u.next.remove(v)
                    v.before.remove(u)

    def build_gates(self):
        for layer in self.vertex_layers:
            self.gate_layers.append([self.gen_gate(v) for v in layer])

    def gen_gate(self, v):
        ft = getattr(v, 'func_type', '').upper().replace('$', '')
        if v.type == VertexType.INPUT: return LogicGates.input_gate(v.name)
        if v.type == VertexType.OUTPUT: return LogicGates.output_gate(v.name)
        if ft == 'RELAY': return LogicGates.relay()
        num_in = getattr(v, 'num_inputs', max(1, len(v.before)))
        if ft in ['AND', 'AND2', '_AND_']: return LogicGates.and_gate(num_in)
        if ft in ['NAND', 'NAND2', '_NAND_']: return LogicGates.nand_gate(num_in)
        if ft in ['OR', 'OR2', '_OR_']: return LogicGates.or_gate(num_in)
        if ft in ['NOR', 'NOR2', '_NOR_']: return LogicGates.nor_gate(num_in)
        if ft in ['XOR', 'XOR2', '_XOR_', 'XNOR', 'XNOR2', '_XNOR_']: return LogicGates.xor_gate()
        if ft in ['INV', 'NOT', 'NOT1', '_NOT_']: return LogicGates._not()
        if ft in ['MUX', '_MUX_']: return LogicGates.mux_gate()
        if ft == '_DLATCH_P_': return LogicGates.d_latch()
        if ft == 'MC_SR_LATCH': return LogicGates.sr_latch()
        if ft == 'MC_T_LATCH': return LogicGates.t_latch()
        if ft.startswith(('_DLATCH', '_DFF', '_SDFF', '_ADFF', '_SR_')):
            raise ValueError(f"Unsupported storage cell {v.func_type}; use a positive-enable D latch or an explicit MC_SR_LATCH/MC_T_LATCH")
        return LogicGates.relay()

    def _get_pins(self, v, g, as_out, with_height=False):
        positions = [(g.x_offset + x, y) for x, y in g.pin_positions(as_out)]
        return positions if with_height else [x for x, y in positions]

    def _input_pins_for_source(self, v, g, source, pointers, with_height=False):
        """Named pins must follow Yosys port roles, not placement order."""
        if isinstance(g.input_offsets, dict):
            source_bits = getattr(source, 'bits', [])
            pins = self._get_pins(v, g, False, with_height)
            return [pin
                    for (port, offset), pin in zip(g.input_offsets.items(), pins)
                    if any(bit in source_bits for bit in v.input_bits.get(port, []))]
        pins = self._get_pins(v, g, False, with_height)
        wanted = getattr(v, 'bits', []) if v.type == VertexType.OUTPUT or getattr(v, 'func_type', '') == 'RELAY' else [bit for bits in getattr(v, 'input_bits', {}).values() for bit in bits]
        if wanted and not set(wanted).intersection(getattr(source, 'bits', [])):
            return []
        ptr = pointers[v]
        if ptr >= len(pins):
            return []
        pointers[v] += 1
        return [pins[ptr]]

    def _output_sources(self, v, g, with_height=False):
        """Associate each physical output with its own signal, including Q/QN."""
        if isinstance(g.output_offsets, dict) and getattr(v, 'output_bits', None):
            pins = self._get_pins(v, g, True, with_height)
            return [(pin,
                     Vertex(v.name, v.type, bits=v.output_bits.get(port, [])))
                    for (port, offset), pin in zip(g.output_offsets.items(), pins)]
        return [(pin, v) for pin in self._get_pins(v, g, True, with_height)]

    def route_channels(self, workers=None):
        # 1. Multi-pass barycenter sweep to minimize crossing connections (Sugiyama method)
        num_layers = len(self.vertex_layers)
        num_sweeps = 12

        for sweep in range(num_sweeps):
            # Forward sweep: sort layer i based on connections to layer i-1 (exclude last layer)
            for i in range(1, num_layers - 1):
                prev_layer = self.vertex_layers[i - 1]
                prev_indices = {v: idx for idx, v in enumerate(prev_layer)}
                current_indices = {v: idx for idx, v in enumerate(self.vertex_layers[i])}
                
                def get_prev_barycenter(item):
                    v, _ = item
                    connected = [prev_indices[u] for u in v.before if u in prev_indices]
                    if not connected:
                        return current_indices[v]
                    return sum(connected) / len(connected)
                
                zipped = list(zip(self.vertex_layers[i], self.gate_layers[i]))
                zipped.sort(key=get_prev_barycenter)
                self.vertex_layers[i] = [v for v, g in zipped]
                self.gate_layers[i] = [g for v, g in zipped]
                
            # Backward sweep: sort layer i based on connections to layer i+1 (exclude first layer)
            for i in range(num_layers - 2, 0, -1):
                next_layer = self.vertex_layers[i + 1]
                next_indices = {v: idx for idx, v in enumerate(next_layer)}
                current_indices = {v: idx for idx, v in enumerate(self.vertex_layers[i])}
                
                def get_next_barycenter(item):
                    v, _ = item
                    connected = [next_indices[w] for w in v.next if w in next_indices]
                    if not connected:
                        return current_indices[v]
                    return sum(connected) / len(connected)
                
                zipped = list(zip(self.vertex_layers[i], self.gate_layers[i]))
                zipped.sort(key=get_next_barycenter)
                self.vertex_layers[i] = [v for v, g in zipped]
                self.gate_layers[i] = [g for v, g in zipped]

        # 2. Assign horizontal gate offsets
        gate_centers = {}
        cx = 0
        for i, v in enumerate(self.vertex_layers[0]):
            g = self.gate_layers[0][i]
            g.x_offset = cx
            gate_centers[v] = cx + (g.size_x / 2)
            cx += g.size_x + 1
            if cx % 2 != 0: cx += 1

        for i in range(len(self.vertex_layers) - 1):
            tvl, tgl = self.vertex_layers[i], self.gate_layers[i]
            bvl, bgl = self.vertex_layers[i+1], self.gate_layers[i+1]
            def get_tx(v):
                placed = []
                for n in v.before + v.next:
                    if n in gate_centers:
                        placed.append(gate_centers[n])
                return sum(placed) / len(placed) if placed else float('inf')
            comb = sorted(list(zip(bvl, bgl)), key=lambda p: get_tx(p[0]))
            self.vertex_layers[i+1], self.gate_layers[i+1] = [p[0] for p in comb], [p[1] for p in comb]
            bvl, bgl = self.vertex_layers[i+1], self.gate_layers[i+1]
            ncx = 0
            for v, g in comb:
                tx = get_tx(v)
                sx = ncx if tx == float('inf') else max(ncx, int(tx - g.size_x / 2))
                if sx % 2 != 0: sx += 1
                g.x_offset = sx
                gate_centers[v] = sx + (g.size_x / 2)
                ncx = sx + g.size_x + 1 # 1-block gap is sufficient
                if ncx % 2 != 0: ncx += 1

        # Phase 2: Pre-calculate routing inputs sequentially
        num_channels = len(self.vertex_layers) - 1
        v_in_ptr = {v: 0 for layer in self.vertex_layers for v in layer}
        
        routing_jobs = []

        for i in range(num_channels):
            tvl, tgl = self.vertex_layers[i], self.gate_layers[i]
            bvl, bgl = self.vertex_layers[i+1], self.gate_layers[i+1]
            nets_in = []

            # 1. Nets from tvl
            for ui, u in enumerate(tvl):
                for (ox, oy), source in self._output_sources(u, tgl[ui], True):
                    net = [(ox, oy, True)]
                    for v in u.next:
                        if v in bvl: # Forward target
                            vi = bvl.index(v)
                            for ix, iy in self._input_pins_for_source(v, bgl[vi], source, v_in_ptr, True):
                                net.append((ix, iy, False))
                        elif v in tvl: # Same-layer target (only if target is RELAY)
                            if getattr(v, 'func_type', '') == 'RELAY':
                                vi = tvl.index(v)
                                for ix, iy in self._input_pins_for_source(v, tgl[vi], source, v_in_ptr, True):
                                    net.append((ix, iy, True))
                    if len(net) > 1:
                        nets_in.append(net)

            # 2. Nets from bvl
            for ui, u in enumerate(bvl):
                for (ox, oy), source in self._output_sources(u, bgl[ui], True):
                    net = []
                    for v in u.next:
                        if v in tvl: # Backward target
                            vi = tvl.index(v)
                            for ix, iy in self._input_pins_for_source(v, tgl[vi], source, v_in_ptr, True):
                                if not net:
                                    net.append((ox, oy, False))
                                net.append((ix, iy, True))
                        elif v in bvl: # Same-layer target (only if source u is RELAY)
                            if getattr(u, 'func_type', '') == 'RELAY':
                                vi = bvl.index(v)
                                for ix, iy in self._input_pins_for_source(v, bgl[vi], source, v_in_ptr, True):
                                    if not net:
                                        net.append((ox, oy, False))
                                    net.append((ix, iy, False))
                    if net:
                        nets_in.append(net)

            ncx = 0
            for g in tgl: ncx = max(ncx, g.x_offset + g.size_x)
            for g in bgl: ncx = max(ncx, g.x_offset + g.size_x)

            # A wool port sometimes emits through dust above it, so the first
            # external wire descends from inside the gate. Preserve THAT pin's
            # headroom even though ordinary flat ports can be covered.
            pin_headroom = set()
            actual_pins = {p for net in nets_in for p in net}
            top_depth = max((g.size_z for g in tgl),default=0)
            for vertices,gates,is_top in ((tvl,tgl,True),(bvl,bgl,False)):
                for v,g in zip(vertices,gates):
                    if is_top and g.size_z != top_depth:
                        continue # The first descending wire is a gate-row extension.
                    edge = g.size_z-1 if is_top else 0
                    for as_out in (False,True):
                        for x,y in self._get_pins(v,g,as_out,True):
                            pin = (x,y,is_top)
                            if pin in actual_pins and 'redstone_wire' in g.blocks.get((x-g.x_offset,y+1,edge),''):
                                pin_headroom.add(pin)

            # Only net coordinates and row width are needed by workers;
            # avoid serializing complete gate blueprints for every channel.
            routing_jobs.append((nets_in, None, None, ncx, i, pin_headroom))

        # Phase 3: Route channels in parallel using ProcessPoolExecutor
        from concurrent.futures import ProcessPoolExecutor, as_completed
        from os import cpu_count
        results = [None] * len(routing_jobs)
        if workers is not None and (type(workers) is not int or workers < 1):
            raise ValueError('workers must be a positive integer')
        worker_count = min(len(routing_jobs), workers or cpu_count() or 1)
        def completed(index, circuit):
            results[index] = circuit
            print(f'  Channel {index+1}/{num_channels}: '
                  f'{circuit.size_x}x{circuit.size_y}x{circuit.size_z}, '
                  f'{circuit.route_stats["seconds"]:.3f}s, '
                  f'{circuit.route_stats["attempts"]} attempts', flush=True)
        if routing_jobs:
            print(f'Routing {num_channels} channels with {worker_count} worker(s)...', flush=True)
        if worker_count == 1:
            for i, job in enumerate(routing_jobs):
                completed(i, parallel_route_worker(*job))
        elif routing_jobs:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(parallel_route_worker, *job): job[4]
                    for job in routing_jobs
                }
                for future in as_completed(futures):
                    i = futures[future]
                    completed(i, future.result())

        for circuit in results:
            self.channels.append(ChannelWrapper(circuit))

    def get_statistics(self):
        stats = {"gate_counts": {}, "total_gates": 0, "max_delay": len(self.vertex_layers)}
        for layer in self.vertex_layers:
            for v in layer:
                ft = getattr(v, 'func_type', v.type)
                stats["gate_counts"][ft] = stats["gate_counts"].get(ft, 0) + 1
                stats["total_gates"] += 1
        return stats
    def save_debug_svg(self, filename): pass

    def gen_circuit(self):
        sx, sy, sz, lz = 0, 3, 0, []
        for i, layer in enumerate(self.gate_layers):
            glx, gly, glz = 0, 0, 0
            for g in layer:
                glx = max(glx, g.x_offset + g.size_x + 2)
                gly, glz = max(gly, g.size_y), max(glz, g.size_z)
            sx, sy = max(sx, glx), max(sy, gly)
            sz += glz; lz.append(glz)
        for c in self.channels:
            sx = max(sx, c.size_x()); sy = max(sy, c.circuit.size_y); sz += c.size_z()
        circ, sources, gr, zoff = Circuit(sx, sy, sz), [], set(), 0
        required_air = set()
        for i, layer in enumerate(self.gate_layers):
            # Place brick floor under the gate layer
            min_x_layer = min(g.x_offset for g in layer) if layer else 0
            max_x_layer = max(g.x_offset + g.size_x for g in layer) if layer else sx
            for lz_idx in range(lz[i]):
                for lx_idx in range(min_x_layer, max_x_layer):
                    circ.set_block(lx_idx, -1, zoff + lz_idx, "minecraft:bricks")
                    
            for j, g in enumerate(layer):
                v = self.vertex_layers[i][j]
                for (lx, ly, lz_pos), b in g.blocks.items():
                    circ.set_block(g.x_offset + lx, ly, zoff + lz_pos, b)
                    if "repeater" in b: gr.add((g.x_offset + lx, ly, zoff + lz_pos))
                outputs = self._get_pins(v, g, True, True)
                for ox, oy in outputs:
                    if g.size_z < lz[i] and 'redstone_wire' in g.blocks.get((ox-g.x_offset,oy+1,g.size_z-1),''):
                        required_air.add((ox,oy+1,zoff+g.size_z))
                    for z in range(g.size_z, lz[i]):
                        circ.set_block(ox, oy-1, zoff + z, "minecraft:white_wool")
                        circ.set_block(ox, oy, zoff + z, "minecraft:redstone_wire")
                if v.type == VertexType.INPUT or (v.type == VertexType.FUNCTION and getattr(v, 'func_type', '') != 'RELAY'):
                    for ox, oy in outputs:
                        sources.append(((ox, oy, zoff + g.size_z), 15, "south"))
            zoff += lz[i]
            if i < len(self.gate_layers) - 1:
                c = self.channels[i]
                for (cx, cy, cz), b in c.gen_channel_circuit().blocks.items(): circ.set_block(cx, cy, zoff + cz, b)
                required_air.update((cx,cy,zoff+cz) for cx,cy,cz in getattr(c.circuit,'required_air',()))
                zoff += c.size_z()
        from router import AIR_BLOCKS
        blocked = [p for p in required_air if circ.blocks.get(p,'minecraft:air').split('[',1)[0] not in AIR_BLOCKS]
        if blocked:
            raise ValueError(f'A block/support cuts routed or gate-port headroom at {sorted(blocked)}')
        circ.required_air = required_air
        return circ, sources, gr
