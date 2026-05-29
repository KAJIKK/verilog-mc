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

def parse_yosys_json(filepath):
    with open(filepath, 'r') as f:
        data = json.load(f)
        
    graph = Graph()
    
    modules = data.get("modules", {})
    if not modules:
        return graph
        
    module_name = list(modules.keys())[0]
    module_data = modules[module_name]
    
    ports = module_data.get("ports", {})
    cells = module_data.get("cells", {})
    
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
                if isinstance(bit, int):
                    bit_readers.setdefault(bit, []).append(v)
                
    # Process Cells (Gates)
    for cell_name, cell_info in cells.items():
        cell_type = cell_info.get("type")
        connections = cell_info.get("connections", {})
        port_directions = cell_info.get("port_directions", {})
        
        v = Vertex(cell_name, VertexType.FUNCTION, func_type=cell_type)
        graph.add_vertex(v)
        
        for conn_name, bits in connections.items():
            direction = port_directions.get(conn_name)
            if not direction:
                if conn_name in ["Y", "Q"]:
                    direction = "output"
                else:
                    direction = "input"
                    
            if direction == "input":
                for bit in bits:
                    if isinstance(bit, int):
                        bit_readers.setdefault(bit, []).append(v)
            elif direction == "output":
                for bit in bits:
                    if isinstance(bit, int):
                        bit_drivers.setdefault(bit, []).append(v)
                    
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
