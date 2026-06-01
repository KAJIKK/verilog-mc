import mcschematic
import shutil
import os
import sys
import netlist_parser
from intermediate_circuit import IntermediateCircuit

# Add repeater_placement to path to import postprocessor
sys.path.append(os.path.join(os.path.dirname(__file__), "repeater_placement"))
from repeater_postprocessor import build_graph

def resolve_redstone_wires(block_map):
    """
    Populates redstone wire properties (north, south, east, west) based on adjacency.
    This is necessary for the repeater postprocessor which relies on these properties.
    """
    new_map = block_map.copy()
    wire_positions = [pos for pos, block in block_map.items() if "minecraft:redstone_wire" in block]
    
    offsets = {
        "north": (0, 0, -1),
        "south": (0, 0, 1),
        "east": (1, 0, 0),
        "west": (-1, 0, 0)
    }
    
    def is_connectable(pos, direction):
        # A wire connects to:
        # 1. Another wire at the same level
        # 2. Another wire one block up
        # 3. Another wire one block down
        # 4. Any block that can receive/emit redstone (simplified: any non-air block for now)
        # However, for the postprocessor's BFS, we mostly care about wire-to-wire.
        
        dx, dy, dz = offsets[direction]
        
        # Same level
        p = (pos[0]+dx, pos[1], pos[2]+dz)
        if p in block_map and ("redstone_wire" in block_map[p] or "repeater" in block_map[p] or "torch" in block_map[p] or "lever" in block_map[p]):
            return "side"
            
        # Up
        p_up = (pos[0]+dx, pos[1]+1, pos[2]+dz)
        if p_up in block_map and "redstone_wire" in block_map[p_up]:
            # Only connects if there's no solid block above the current wire
            if (pos[0], pos[1]+1, pos[2]) not in block_map or "air" in block_map[(pos[0], pos[1]+1, pos[2])]:
                return "up"
        
        # Down
        p_down = (pos[0]+dx, pos[1]-1, pos[2]+dz)
        if p_down in block_map and "redstone_wire" in block_map[p_down]:
            # Only connects if there's no solid block above the lower wire
            if (pos[0]+dx, pos[1], pos[2]+dz) not in block_map or "air" in block_map[(pos[0]+dx, pos[1], pos[2]+dz)]:
                return "side" # In MC, descending wires show as "side" connection on the upper wire
                
        return "none"

    for pos in wire_positions:
        props = []
        for d in ["north", "south", "east", "west"]:
            conn = is_connectable(pos, d)
            if conn != "none":
                props.append(f"{d}={conn}")
        
        prop_str = "[" + ",".join(props) + "]" if props else ""
        new_map[pos] = f"minecraft:redstone_wire{prop_str}"
        
    return new_map

def generate_circuit_schematic(json_filepath, filename):
    print(f"Parsing {json_filepath}...")
    graph = netlist_parser.parse_yosys_json(json_filepath)
    
    print("Building intermediate circuit layers...")
    ic = IntermediateCircuit()
    ic.load_graph(graph)
    
    print("Generating gate blueprints...")
    ic.build_gates()
    
    print("Routing channels...")
    ic.route_channels()
    
    print("Assembling final circuit...")
    circuit, sources, gate_repeaters = ic.gen_circuit()
    
    # Save debug SVG
    svg_filename = f"{filename}_debug.svg"
    ic.save_debug_svg(svg_filename)
    
    # Report Statistics
    stats = ic.get_statistics()
    print("\n" + "="*30)
    print(" CIRCUIT STATISTICS ")
    print("="*30)
    print(f"Dimensions: {circuit.size_x}x{circuit.size_y}x{circuit.size_z} (WxHxL)")
    print(f"Max Delay:  {stats['max_delay']} layers")
    print(f"Total Gates: {stats['total_gates']}")
    print("-" * 15)
    for gtype, count in sorted(stats["gate_counts"].items()):
        print(f"  {gtype:<10}: {count}")
    print("="*30 + "\n")
    
    # Apply Repeater Placement Postprocessor
    print("Running repeater placement postprocessor...")
    
    # build_graph needs a block_map and sources.
    # It expects sources to be (pos, power, direction) where pos is (x, y, z)
    # Our circuit.blocks is already (x, y, z) -> block_string
    
    # Clean non-gate repeaters for the postprocessor (sanity check)
    block_map = {}
    for pos, block in circuit.blocks.items():
        if "repeater" in block and pos not in gate_repeaters:
            block_map[pos] = "minecraft:redstone_wire"
        else:
            block_map[pos] = block

    # Resolve bare wires to have properties for the postprocessor
    resolved_map = resolve_redstone_wires(block_map)

    try:
        _, repeaters = build_graph(resolved_map, sources)
        print(f"Postprocessor placed {len(repeaters)} repeaters.")
        # Apply repeaters to the circuit
        for pos, direction in repeaters.items():
            circuit.set_block(pos[0], pos[1], pos[2], f"minecraft:repeater[facing={direction}]")
    except Exception as e:
        print(f"WARNING: Repeater placement postprocessor failed: {e}")
        print("Falling back to bare redstone wires.")

    schem = mcschematic.MCSchematic()
    
    # Place stone brick base
    for z in range(-1, circuit.size_z + 1):
        for x in range(-1, circuit.size_x + 1):
            schem.setBlock((x, -1, z), "minecraft:stone_bricks")
            
    # Place all blocks
    for (x, y, z), block in circuit.blocks.items():
        schem.setBlock((x, y, z), block)
        
    print("Saving schematic...")
    schem.save(".", filename, mcschematic.Version.JE_1_21_4)
    print(f"Successfully generated {filename}.schem")

    # Copy to WorldEdit schematics directory
    target_dir = "/home/kajat/.local/share/PrismLauncher/instances/Fabulously Optimized(1)/minecraft/config/worldedit/schematics"
    os.makedirs(target_dir, exist_ok=True)
    
    source_file = f"{filename}.schem"
    target_file = os.path.join(target_dir, source_file)
    shutil.copy2(source_file, target_file)
    print(f"Copied {filename}.schem to {target_dir}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_schem.py <path_to_json>")
        sys.exit(1)
        
    filepath = sys.argv[1]
    filename = os.path.splitext(os.path.basename(filepath))[0]
    generate_circuit_schematic(filepath, filename)
