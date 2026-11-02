import json
import sys

class VertexType:
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    FUNCTION = "FUNCTION"

class Vertex:
    def __init__(self, name, v_type, **kwargs):
        self.name = name
        self.type = v_type
        self.next = []    # List of connected Vertices (output of this vertex goes to them)
        self.before = []  # List of connected Vertices (input to this vertex comes from them)
        for k, v in kwargs.items():
            setattr(self, k, v)

    def add_next(self, v):
        if v not in self.next:
            self.next.append(v)

    def add_before(self, v):
        if v not in self.before:
            self.before.append(v)

    def __repr__(self):
        type_str = getattr(self, 'func_type', self.type)
        return f"[{self.type}] {self.name} ({type_str})"

class Graph:
    def __init__(self):
        self.vertices = {}
        self.lut_stats = {}
        
    def add_vertex(self, v):
        self.vertices[v.name] = v
        
    def add_edge(self, v1, v2):
        v1.add_next(v2)
        v2.add_before(v1)

    def print_graph(self):
        print(f"Graph with {len(self.vertices)} vertices:")
        for name, v in self.vertices.items():
            print(f"{v}")
            for n in v.next:
                print(f"  -> {n.name}")

def parse_yosys_json(filepath, *, pack_luts=True,hybrid_luts=False,gate_cost_scale=1.0):
    with open(filepath, 'r') as f:
        data = json.load(f)
    return parse_yosys_data(data,pack_luts=pack_luts,hybrid_luts=hybrid_luts,gate_cost_scale=gate_cost_scale)


def parse_yosys_data(data, *, pack_luts=True,hybrid_luts=False,gate_cost_scale=1.0):
    """Parse an in-memory netlist as well as generated JSON files."""
    graph = Graph()
    
    modules = data.get("modules", {})
    if not modules:
        return graph
        
    # Library black boxes also appear in Yosys JSON; select the actual design.
    def attribute_set(module, name):
        value = module.get('attributes', {}).get(name, 0)
        return int(value, 2) != 0 if isinstance(value, str) else bool(value)
    tops = [name for name, module in modules.items() if attribute_set(module, 'top')]
    designs = [name for name, module in modules.items() if not attribute_set(module, 'blackbox')]
    module_name = (tops or designs or list(modules))[0]
    module_data = modules[module_name]
    
    ports = module_data.get("ports", {})
    from lut_mapping import pack_lut_cells,decode_lut
    mapped = attribute_set(module_data,'mc_hybrid_mapped')
    cells,graph.lut_stats = pack_lut_cells(module_data,pack_luts and not mapped,
                                         hybrid=hybrid_luts and not mapped,gate_cost_scale=gate_cost_scale)
    if mapped:
        graph.lut_stats = json.loads(module_data['attributes']['mc_mapping_stats'])
    
    bit_drivers = {}
    bit_readers = {}
    
    # Process Ports
    for port_name, port_info in ports.items():
        direction = port_info.get("direction")
        bits = port_info.get("bits", [])
        
        if direction == "input":
            for i, bit in enumerate(bits):
                name = f"{port_name}[{i}]" if len(bits) > 1 else port_name
                v = Vertex(name, VertexType.INPUT, bits=[bit])
                graph.add_vertex(v)
                if isinstance(bit, int):
                    bit_drivers.setdefault(bit, []).append(v)
                
        elif direction == "output":
            for i, bit in enumerate(bits):
                name = f"{port_name}[{i}]" if len(bits) > 1 else port_name
                v = Vertex(name, VertexType.OUTPUT, bits=[bit])
                graph.add_vertex(v)
                if isinstance(bit, int) or bit in ('0','1'):
                    bit_readers.setdefault(bit, []).append(v)
                
    # Process Cells (Gates)
    for cell_name, cell_info in cells.items():
        cell_type = cell_info.get("type")
        connections = cell_info.get("connections", {})
        port_directions = cell_info.get("port_directions", {})
        
        v = Vertex(cell_name, VertexType.FUNCTION, func_type=cell_type,
                   input_bits={}, output_bits={}, bits=[],parameters=cell_info.get('parameters',{}))
        graph.add_vertex(v)

        if cell_type == 'MC_LUT':
            lut = decode_lut(cell_info)
            v.func_type = 'LUT'
            v.input_bits = {f'I{i}':[bit] for i,bit in enumerate(lut.inputs)}
            v.output_bits = {f'O{i}':[bit] for i,bit in enumerate(lut.outputs)}
            v.bits = list(lut.outputs)
            v.lut_data = lut.data
            for bit in lut.inputs:
                bit_readers.setdefault(bit,[]).append(v)
            for bit in lut.outputs:
                bit_drivers.setdefault(bit,[]).append(v)
            continue
        
        for conn_name, bits in connections.items():
            direction = port_directions.get(conn_name)
            if not direction:
                if conn_name in ["Y", "Q", "QN"]:
                    direction = "output"
                else:
                    direction = "input"
                    
            if direction == "input":
                v.input_bits[conn_name] = bits
                for bit in bits:
                    if isinstance(bit, int) or bit in ('0','1'):
                        bit_readers.setdefault(bit, []).append(v)
            elif direction == "output":
                v.output_bits[conn_name] = bits
                v.bits.extend(bits)
                for bit in bits:
                    if isinstance(bit, int):
                        bit_drivers.setdefault(bit, []).append(v)
                    
    # Literal rails are explicit zero-input LUTs, not undriven lamp/wool pins.
    for literal in ('0','1'):
        if literal in bit_readers:
            name = f'constant_{literal}'
            while name in graph.vertices:
                name = '_'+name
            constant = Vertex(name,VertexType.FUNCTION,func_type='LUT',bits=[literal],
                              input_bits={},output_bits={'O0':[literal]},lut_data=(int(literal),))
            graph.add_vertex(constant)
            bit_drivers[literal] = [constant]

    # Connect drivers to readers
    for bit, drivers in bit_drivers.items():
        if bit in bit_readers:
            for driver in drivers:
                for reader in bit_readers[bit]:
                    graph.add_edge(driver, reader)
                    
    return graph

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python netlist_parser.py <path_to_json>")
        sys.exit(1)
        
    filepath = sys.argv[1]
    g = parse_yosys_json(filepath)
    g.print_graph()
