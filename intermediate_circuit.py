from netlist_parser import VertexType, Vertex, Graph
from router import route as route_new
from logic_gates import LogicGates, Circuit

def parallel_route_worker(nets_in, tgl, bgl, ncx, channel_idx):
    if nets_in:
        from router import route as route_new
        return route_new(nets_in, tgl, bgl)
    else:
        return Circuit(ncx, 3, 1)

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

        relay_count = 0
        edges = []
        for v in vertices:
            for n in list(v.next):
                edges.append((v, n))

        for u, v in edges:
            ul, vl = self.v_to_layer[u], self.v_to_layer[v]

            if vl <= ul:
                # Backward or Same-layer edge!
                # We need a chain of relays at layers ul, ul-1, ..., vl
                prev = u
                for r_layer in range(ul, vl - 1, -1):
                    relay = Vertex(f"relay_backward_{relay_count}", VertexType.FUNCTION, func_type="RELAY")
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

            elif vl > ul + 1:
                # Forward edge spanning multiple layers
                # We need a chain of relays at layers ul+1, ul+2, ..., vl-1
                prev = u
                for r_layer in range(ul + 1, vl):
                    relay = Vertex(f"relay_forward_{relay_count}", VertexType.FUNCTION, func_type="RELAY")
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
        return LogicGates.relay()

    def _get_pins(self, v, g, as_out):
        off = (getattr(g, 'output_offsets', None) if as_out else getattr(g, 'input_offsets', None))
        if off:
            if isinstance(off, dict): off = list(off.values())
            return [g.x_offset + x for x in off]
        cnt = (getattr(g, 'num_outputs', 1) if as_out else getattr(g, 'num_inputs', 1))
        spc = (getattr(g, 'output_spacing', 1) if as_out else getattr(g, 'input_spacing', 1))
        return [g.x_offset + (i * (1 + spc)) for i in range(cnt)]

    def route_channels(self):
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
                oxs = self._get_pins(u, tgl[ui], True)
                for pi, ox in enumerate(oxs):
                    net = [(ox, 0, True)]
                    for v in u.next:
                        if v in bvl: # Forward target
                            vi = bvl.index(v)
                            ixs = self._get_pins(v, bgl[vi], False)
                            ptr = v_in_ptr[v]
                            if ptr < len(ixs):
                                net.append((ixs[ptr], 0, False))
                                v_in_ptr[v] += 1
                        elif v in tvl: # Same-layer target (only if target is RELAY)
                            if getattr(v, 'func_type', '') == 'RELAY':
                                vi = tvl.index(v)
                                ixs = self._get_pins(v, tgl[vi], False)
                                ptr = v_in_ptr[v]
                                if ptr < len(ixs):
                                    net.append((ixs[ptr], 0, True))
                                    v_in_ptr[v] += 1
                    if len(net) > 1:
                        nets_in.append(net)

            # 2. Nets from bvl
            for ui, u in enumerate(bvl):
                oxs = self._get_pins(u, bgl[ui], True)
                for pi, ox in enumerate(oxs):
                    net = []
                    for v in u.next:
                        if v in tvl: # Backward target
                            vi = tvl.index(v)
                            ixs = self._get_pins(v, tgl[vi], False)
                            ptr = v_in_ptr[v]
                            if ptr < len(ixs):
                                if not net:
                                    net.append((ox, 0, False))
                                net.append((ixs[ptr], 0, True))
                                v_in_ptr[v] += 1
                        elif v in bvl: # Same-layer target (only if source u is RELAY)
                            if getattr(u, 'func_type', '') == 'RELAY':
                                vi = bvl.index(v)
                                ixs = self._get_pins(v, bgl[vi], False)
                                ptr = v_in_ptr[v]
                                if ptr < len(ixs):
                                    if not net:
                                        net.append((ox, 0, False))
                                    net.append((ixs[ptr], 0, False))
                                    v_in_ptr[v] += 1
                    if net:
                        nets_in.append(net)

            ncx = 0
            for g in tgl: ncx = max(ncx, g.x_offset + g.size_x)
            for g in bgl: ncx = max(ncx, g.x_offset + g.size_x)

            routing_jobs.append((nets_in, tgl, bgl, ncx, i))

        # Phase 3: Route channels in parallel using ProcessPoolExecutor
        from concurrent.futures import ProcessPoolExecutor
        results = [None] * len(routing_jobs)
        
        with ProcessPoolExecutor() as executor:
            futures = {
                executor.submit(parallel_route_worker, nets_in, tgl, bgl, ncx, i): i
                for nets_in, tgl, bgl, ncx, i in routing_jobs
            }
            for future in futures:
                i = futures[future]
                results[i] = future.result()

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
            sx = max(sx, c.size_x()); sz += c.size_z()
        circ, sources, gr, zoff = Circuit(sx, sy, sz), [], set(), 0
        for i, layer in enumerate(self.gate_layers):
            # Place brick floor under the gate layer
            for lz_idx in range(lz[i]):
                for lx_idx in range(sx):
                    circ.set_block(lx_idx, -1, zoff + lz_idx, "minecraft:bricks")
                    
            for j, g in enumerate(layer):
                v = self.vertex_layers[i][j]
                for (lx, ly, lz_pos), b in g.blocks.items():
                    circ.set_block(g.x_offset + lx, ly, zoff + lz_pos, b)
                    if "repeater" in b: gr.add((g.x_offset + lx, ly, zoff + lz_pos))
                oxs = self._get_pins(v, g, True)
                for ptr, ox in enumerate(oxs):
                    for z in range(g.size_z, lz[i]): circ.set_block(ox, 0, zoff + z, "minecraft:redstone_wire")
                if v.type == VertexType.INPUT or (v.type == VertexType.FUNCTION and getattr(v, 'func_type', '') != 'RELAY'):
                    outs = getattr(g, 'output_offsets', None) or [0]
                    if isinstance(outs, dict): outs = list(outs.values())
                    for o in outs: sources.append(((g.x_offset + o, 0, zoff + g.size_z), 15, "south"))
            zoff += lz[i]
            if i < len(self.gate_layers) - 1:
                c = self.channels[i]
                for (cx, cy, cz), b in c.gen_channel_circuit().blocks.items(): circ.set_block(cx, cy, zoff + cz, b)
                zoff += c.size_z()
        return circ, sources, gr
