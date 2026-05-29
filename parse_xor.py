import mcschematic
import os

def parse_schem(filepath):
    schem = mcschematic.MCSchematic(filepath)
    structure = schem.getStructure()
    
    blocks = structure.getBlockStates()
    palette = structure.getBlockPalette()
    entities = structure.getBlockEntities()

    # mcschematic internals:
    # _blockStates is {(x, y, z): palette_id}
    # _blockPalette is {palette_id: block_data_string, block_data_string: palette_id}
    
    print(f"Parsing {filepath}...")
    min_x, min_y, min_z = float('inf'), float('inf'), float('inf')
    max_x, max_y, max_z = float('-inf'), float('-inf'), float('-inf')
    
    found_blocks = []
    
    for (x, y, z), palette_id in blocks.items():
        block_data = palette[palette_id]
        # Ignore stone bricks (the base) and air if present
        if "stone_bricks" in block_data or "air" in block_data:
            continue
            
        found_blocks.append(((x, y, z), block_data))
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        min_z = min(min_z, z)
        max_x = max(max_x, x)
        max_y = max(max_y, y)
        max_z = max(max_z, z)

    # Normalize to (0,0,0)
    print(f"Dimensions: {max_x - min_x + 1}x{max_y - min_y + 1}x{max_z - min_z + 1}")
    print("Blocks:")
    for (x, y, z), data in sorted(found_blocks, key=lambda b: (b[0][1], b[0][2], b[0][0])):
        norm_pos = (x - min_x, y - min_y, z - min_z)
        print(f"  gate.set_block{norm_pos}, \"{data}\")")

if __name__ == "__main__":
    parse_schem("xor.schem")
