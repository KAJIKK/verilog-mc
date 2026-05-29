import mcschematic
import shutil
import os
import sys
import netlist_parser
from intermediate_circuit import IntermediateCircuit

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
    circuit = ic.gen_circuit()
    
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
