import nbtlib
import sys
import json

def parse_schem(filepath):
    nbt = nbtlib.load(filepath)
    schem = nbt['Schematic']
    width = int(schem['Width'])
    height = int(schem['Height'])
    length = int(schem['Length'])
    
    blocks_node = schem['Blocks']
    palette = blocks_node['Palette']
    data = blocks_node['Data']
    
    # Invert palette
    id_to_block = {int(v): str(k) for k, v in palette.items()}
    
    result_blocks = {}
    
    # Sponge format index: (y * length + z) * width + x
    for y in range(height):
        for z in range(length):
            for x in range(width):
                idx = (y * length + z) * width + x
                block_id = int(data[idx])
                block_name = id_to_block[block_id]
                
                if "air" in block_name or "stone_bricks" in block_name:
                    continue
                
                result_blocks[f"{x},{y},{z}"] = block_name

    gate_data = {
        "size": [width, height, length],
        "blocks": result_blocks
    }
    
    print(json.dumps(gate_data, indent=2))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_gate.py <schem_file>")
    else:
        parse_schem(sys.argv[1])
