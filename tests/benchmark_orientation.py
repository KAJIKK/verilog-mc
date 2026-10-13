"""Experimental 180-degree gate placement; production placement is untouched.

python3 -m tests.benchmark_orientation --design output/adder4.json
Candidates preserve I/O boundary rows. Real per-signal feedthroughs connect
opposite-facing ports to the correct channels; they are not free connections.
"""
import argparse
import contextlib
import io
import json
import re
from time import perf_counter

from intermediate_circuit import IntermediateCircuit, ChannelWrapper
from logic_gates import Gate, Circuit
from netlist_parser import Vertex, VertexType, parse_yosys_json
from router import route, RoutingError, AIR_BLOCKS
from generate_schem import resolve_redstone_wires
from repeater_postprocessor import build_graph


def reverse_gate(gate):
    """Rotate geometry, state directions and physical pins together about Y."""
    result = Gate(gate.size_x,gate.size_y,gate.size_z,gate.num_inputs,gate.num_outputs)
    directions = {'north':'south','south':'north','east':'west','west':'east'}
    for (x,y,z),block in gate.blocks.items():
        result.set_block(gate.size_x-1-x,y,gate.size_z-1-z,
                         re.sub(r'\b(north|south|east|west)\b',
                                lambda m:directions[m[0]],block))
    def pins(offsets,as_out):
        positions = [[gate.size_x-1-x,y] for x,y in gate.pin_positions(as_out)]
        return dict(zip(offsets,positions)) if isinstance(offsets,dict) else positions
    result.input_offsets = pins(gate.input_offsets,False)
    result.output_offsets = pins(gate.output_offsets,True)
    result.x_offset = 0
    return result


def base_rows(path):
    ic = IntermediateCircuit()
    with contextlib.redirect_stdout(io.StringIO()):
        ic.load_graph(parse_yosys_json(path))
    return [[v.name for v in vs if getattr(v,'func_type','') != 'RELAY']
            for vs in ic.vertex_layers]


class OrientedCircuit(IntermediateCircuit):
    def __init__(self,path,rows,reversed_names):
        super().__init__()
        graph = parse_yosys_json(path)
        self.vertex_layers = [[graph.vertices[name] for name in row] for row in rows]
        self.v_to_layer = {v:i for i,vs in enumerate(self.vertex_layers) for v in vs}
        self.reversed = {graph.vertices[name] for name in reversed_names}
        self.gates = {v:self.gen_gate(v) for v in self.v_to_layer}
        for v,g in list(self.gates.items()):
            self.gates[v] = reverse_gate(g) if v in self.reversed else g
            self.gates[v].x_offset = 0
        self.nets = [[] for _ in range(len(rows)-1)]
        self.feeds = set()
        pointers = {v:0 for v in self.gates}
        # Pin identity is fixed before placement (only list-based logic pins
        # are interchangeable). Q/QN and all named input roles stay distinct.
        for u in graph.vertices.values():
            gate = self.gates[u]
            for index,((ox,oy),source) in enumerate(self._output_sources(u,gate,True)):
                destinations = []
                for v in u.next:
                    for ix,iy in self._input_pins_for_source(v,self.gates[v],source,pointers,True):
                        destinations.append((self.port_channel(v,False),(v,ix,iy)))
                if not destinations:
                    continue
                origin = self.port_channel(u,True)
                lo,hi = min([origin]+[c for c,_ in destinations]),max([origin]+[c for c,_ in destinations])
                if lo < 0 or hi >= len(self.nets):
                    raise ValueError('A port faces outside the available channels')
                feeds = {}
                for row in range(lo+1,hi+1):
                    relay = Vertex(f'feed_{u.name}_{index}_{row}',VertexType.FUNCTION,
                                   func_type='RELAY',bits=source.bits)
                    self.vertex_layers[row].append(relay)
                    self.v_to_layer[relay] = row
                    self.gates[relay] = self.gen_gate(relay)
                    self.gates[relay].x_offset = 0
                    self.feeds.add(relay)
                    feeds[row] = (relay,0,0)
                for channel in range(lo,hi+1):
                    start = (u,ox,oy) if channel == origin else feeds[channel+1 if channel < origin else channel]
                    ends = [pin for c,pin in destinations if c == channel]
                    if channel <= origin and channel > lo:
                        ends.append(feeds[channel])
                    if channel >= origin and channel < hi:
                        ends.append(feeds[channel+1])
                    self.nets[channel].append((start,ends))
        self.gate_layers = [[self.gates[v] for v in vs] for vs in self.vertex_layers]

    def port_channel(self,v,as_out):
        return self.v_to_layer[v] + (0 if as_out != (v in self.reversed) else -1)

    def _placement_edges(self):
        return [(i,u,ox,oy,v,ix,iy,self.v_to_layer[u] == self.v_to_layer[v])
                for i,nets in enumerate(self.nets) for (u,ox,oy),ends in nets
                for v,ix,iy in ends]

    def route_oriented(self):
        self.place_gates()
        depths = [max((g.size_z for g in gs),default=1) for gs in self.gate_layers]
        for i,nets in enumerate(self.nets):
            def coordinate(pin):
                v,x,y = pin
                return (self.gates[v].x_offset+x,y,self.v_to_layer[v] == i)
            routing_nets = [[coordinate(start)]+[coordinate(p) for p in ends]
                            for start,ends in nets]
            clearance = set()
            for net in routing_nets:
                for x,y,is_top in net:
                    row = i if is_top else i+1
                    for v in self.vertex_layers[row]:
                        g = self.gates[v]
                        if v in self.feeds:
                            continue
                        # Forward gates are flush north, reversed gates south.
                        shift = depths[row]-g.size_z if v in self.reversed else 0
                        z = depths[row]-1-shift if is_top else -shift
                        if 'redstone_wire' in g.blocks.get((x-g.x_offset,y+1,z),''):
                            clearance.add((x,y,is_top))
            width = max(g.x_offset+g.size_x for gs in self.gate_layers[i:i+2] for g in gs)
            # Identical explicit budgets for forward and reversed experiments.
            circuit = route(routing_nets,min_width=width,pin_headroom=clearance,
                            attempts=3,max_states=4000,max_length=17,max_height=9)
            self.channels.append(ChannelWrapper(circuit))

    def assemble(self):
        depths = [max((g.size_z for g in gs),default=1) for gs in self.gate_layers]
        width = max([g.x_offset+g.size_x+2 for g in self.gates.values()]+
                    [c.size_x() for c in self.channels])
        height = max([3]+[g.size_y for g in self.gates.values()]+
                     [c.circuit.size_y for c in self.channels])
        length = sum(depths)+sum(c.size_z() for c in self.channels)
        circuit = Circuit(width,height,length)
        sources, gate_repeaters, required_air = [],set(),set()
        routing_positions = set()
        zoff = 0
        for row,vs in enumerate(self.vertex_layers):
            depth = depths[row]
            for v in vs:
                g = self.gates[v]
                shift = depth-g.size_z if v in self.reversed else 0
                for (x,y,z),block in g.blocks.items():
                    pos = (g.x_offset+x,y,zoff+shift+z)
                    if pos in circuit.blocks:
                        raise ValueError('Overlapping gate geometry')
                    circuit.set_block(*pos,block)
                    if v in self.feeds and 'redstone_wire' in block:
                        routing_positions.add(pos)
                    if 'repeater' in block:
                        gate_repeaters.add(pos)
                for x in range(g.x_offset,g.x_offset+g.size_x):
                    for z in range(depth):
                        circuit.set_block(x,-1,zoff+z,'minecraft:bricks')
                for x,y in g.pin_positions(True):
                    if v in self.feeds:
                        extension = range(1,depth)
                    elif v in self.reversed:
                        extension = range(shift)
                        if shift and 'redstone_wire' in g.blocks.get((x,y+1,0),''):
                            required_air.add((g.x_offset+x,y+1,zoff+shift-1))
                    else:
                        extension = range(g.size_z,depth)
                        if g.size_z < depth and 'redstone_wire' in g.blocks.get((x,y+1,g.size_z-1),''):
                            required_air.add((g.x_offset+x,y+1,zoff+g.size_z))
                    for z in extension:
                        circuit.set_block(g.x_offset+x,y-1,zoff+z,'minecraft:white_wool')
                        circuit.set_block(g.x_offset+x,y,zoff+z,'minecraft:redstone_wire')
                        routing_positions.add((g.x_offset+x,y,zoff+z))
                    if v not in self.feeds and v.type != VertexType.OUTPUT:
                        facing = 'north' if v in self.reversed else 'south'
                        # Source power starts at the physical output, BEFORE
                        # padding extensions. Those extensions consume power.
                        z = zoff+shift-1 if v in self.reversed else zoff+g.size_z
                        sources.append(((g.x_offset+x,y,z),15,facing))
            zoff += depth
            if row < len(self.channels):
                channel = self.channels[row].circuit
                for (x,y,z),block in channel.blocks.items():
                    circuit.set_block(x,y,zoff+z,block)
                required_air.update((x,y,zoff+z) for x,y,z in channel.required_air)
                routing_positions.update((x,y,zoff+z) for wires in channel.net_wires for x,y,z in wires)
                zoff += channel.size_z
        if any(circuit.blocks.get(p,'minecraft:air').split('[',1)[0] not in AIR_BLOCKS for p in required_air):
            raise ValueError('Blocked gate-port or slope headroom')
        circuit.required_air = required_air
        circuit.routing_positions = routing_positions
        return circuit,sources,gate_repeaters


def candidates(rows):
    yield 'forward',rows,set()
    for i,row in enumerate(rows[1:-1],1):
        for name in row:
            yield 'reverse:'+name,rows,{name}
        if len(row) > 1:
            yield f'reverse_row:{i}',rows,set(row)
    for i in range(1,len(rows)-2):
        folded = rows[:i]+[rows[i]+rows[i+1]]+rows[i+2:]
        yield f'fold_rows:{i},{i+1}',folded,set(rows[i+1])
        yield f'fold_rows_forward:{i},{i+1}',folded,set()


def evaluate(path,label,rows,reversed_names,export=None):
    started = perf_counter()
    try:
        ic = OrientedCircuit(path,rows,reversed_names)
        ic.route_oriented()
        circuit,sources,gate_repeaters = ic.assemble()
        with contextlib.redirect_stdout(io.StringIO()):
            graph,repeaters = build_graph(resolve_redstone_wires(circuit.blocks),sources)
        # Unlike real gate logic, all routing dust must be reached by the
        # postprocessor's source model, including reversed-output extensions.
        if any(graph.get(p,{}).get('power',0) <= 0 for p in circuit.routing_positions):
            raise ValueError('Postprocessor left unpowered routing')
        if export:
            import mcschematic
            from pathlib import Path
            schematic = mcschematic.MCSchematic()
            # Match production exports: a continuous stone-brick base with a
            # one-block border, then the actual supports and gate-row floors.
            xs = [p[0] for p in circuit.blocks]
            zs = [p[2] for p in circuit.blocks]
            for z in range(min(zs)-1,max(zs)+2):
                for x in range(min(xs)-1,max(xs)+2):
                    schematic.setBlock((x,-1,z),'minecraft:stone_bricks')
            for pos,block in circuit.blocks.items():
                if pos in repeaters:
                    block = f'minecraft:repeater[facing={repeaters[pos]}]'
                schematic.setBlock(pos,block)
            target = Path(export)
            schematic.save(str(target.parent),target.stem,mcschematic.Version.JE_1_21_4)
        return {'candidate':label,'dimensions':[circuit.size_x,circuit.size_y,circuit.size_z],
                'footprint':circuit.size_x*circuit.size_z,'feedthroughs':len(ic.feeds),
                'routing_repeaters':len(repeaters),'reversed_gates':sorted(reversed_names),
                'seconds':perf_counter()-started}
    except (RoutingError,ValueError) as error:
        return {'candidate':label,'error':str(error),'seconds':perf_counter()-started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design',required=True)
    parser.add_argument('--candidate',action='append',help='Exact candidate name; default evaluates all')
    parser.add_argument('--output',help='Optional JSON report path')
    parser.add_argument('--export',help='Optional schematic path; requires exactly one --candidate')
    args = parser.parse_args()
    if args.export and (not args.candidate or len(args.candidate) != 1):
        parser.error('--export requires exactly one --candidate')
    rows = base_rows(args.design)
    results = []
    for label,layout,reversed_names in candidates(rows):
        if args.candidate and label not in args.candidate:
            continue
        result = evaluate(args.design,label,layout,reversed_names,args.export)
        results.append(result)
        print(json.dumps(result),flush=True)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(json.dumps({
            'design':args.design,
            'routing_budget':{'attempts':3,'max_states':4000,'max_length':17,'max_height':9},
            'notes':['I/O boundary rows stay fixed; 180-degree Y rotations only.',
                     'Physical input assignments are fixed before placement; production allows commutative input reassignment.',
                     'Single-gate flips, whole-row flips and one adjacent-row fold at a time; not an exhaustive orientation search.',
                     'Offline postprocessing checks routing power; functional validity requires live testing.'],
            'results':results},indent=2)+'\n')


if __name__ == '__main__':
    main()
