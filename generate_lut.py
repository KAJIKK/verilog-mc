import mcschematic
import os
import shutil

def generate_lut(num_inputs, num_outputs, lut_data, filename="lut"):
    # 0. Limits and Validation
    if num_inputs > 4:
        raise ValueError(f"Too many inputs: {num_inputs} (max 4)")
    if num_outputs > 8:
        raise ValueError(f"Too many outputs: {num_outputs} (max 8)")
    if len(lut_data) != (1 << num_inputs):
        raise ValueError(f"Data length mismatch: expected {1 << num_inputs}, got {len(lut_data)}")
    for val in lut_data:
        if val < 0 or val >= (1 << num_outputs):
            raise ValueError(f"Data value {val} out of range for {num_outputs} outputs")

    schem = mcschematic.MCSchematic()
    
    BLUE = "minecraft:blue_wool"
    WHITE = "minecraft:white_wool"
    RED = "minecraft:red_wool"
    REPEATER = "minecraft:repeater"
    WIRE = "minecraft:redstone_wire"
    AIR = "minecraft:air"
    TORCH = "minecraft:redstone_wall_torch"

    num_rows = 1 << num_inputs
    
    # 1. Blue Wool (Output Columns)
    # Columns at x=0, 2, 4, 6...
    for m in range(num_outputs):
        x = 2 * m
        for z in range(2, num_rows * 2 + 1):
            schem.setBlock((x, 0, z), BLUE)
            if z % 16 == 1 and z != 1:  # Place a repeater every 16 blocks for signal strength
                schem.setBlock((x, 1, z), f"{REPEATER}[facing=north]")
            else:
                schem.setBlock((x, 1, z), WIRE)
            
    # 2. White Wool (Rows)
    # Rows at z=1, 3, 5... (odd)
    # Each row is a full bar across the width
    width = 2 * max(num_inputs, num_outputs)
    for i in range(num_rows):
        z = 2 * i + 1
        for x in range(width):
            schem.setBlock((x, 2, z), WHITE)
            schem.setBlock((x, 3, z), WIRE)

        # Encoder Logic: Torches pull up Blue wire if bit is 1
        # Flip index because decoder has 0 at the back
        mapped_input = num_rows - 1 - i
        val = lut_data[mapped_input] if mapped_input < len(lut_data) else 0
        # Debug string shows bits from 0 to N-1 (Left to Right matching X=0, 2, 4...)
        torch_str = "".join(["1" if (val >> m) & 1 == 1 else "0" for m in range(num_outputs)])
        print(f"{mapped_input}->{val} {val:0{num_outputs}b} Torches: {torch_str}")
        for m in range(num_outputs):
            if (val >> m) & 1 == 1:
                # Bit m maps to Column m at x = 2*m
                x_out = 2 * m
                schem.setBlock((x_out, 2, z + 1), f"{TORCH}[facing=south]")
            
    # 3. Red Wool (Decoder & Address)

    # Address lines at x=1, 3, 5, 7... at y=4
    for n in range(num_inputs):
        x = 2 * n + 1
        for z in range(1, num_rows * 2):
            schem.setBlock((x, 4, z), RED)
            schem.setBlock((x, 5, z), WIRE)
            
    # Decoder Logic at y=3, z=even
    # Bit 0 -> x=1, Bit 1 -> x=3, Bit 2 -> x=5, Bit 3 -> x=7
    # mapping: Bit j -> x = 2 * j + 1
    for i in range(num_rows):
        z = 2 * i
        for j in range(num_inputs):
            x = 2 * j + 1
            if (i >> j) & 1:
                schem.setBlock((x, 3, z), RED)
                schem.setBlock((x, 4, z), f"{REPEATER}[facing=north]")  # Repeater for bit=1
                schem.setBlock((x, 5, z), AIR)
            else:
                schem.setBlock((x-1, 4, z+1), f"{TORCH}[facing=west]")  # Torch for bit=0

    print("Saving wool-only schematic...")
    schem.save(".", filename, mcschematic.Version.JE_1_21_4)
    
    target_dir = "/home/kajat/.local/share/PrismLauncher/instances/Fabulously Optimized(1)/minecraft/config/worldedit/schematics"
    os.makedirs(target_dir, exist_ok=True)
    shutil.copy2(f"{filename}.schem", os.path.join(target_dir, f"{filename}.schem"))
    print(f"Copied {filename}.schem to {target_dir}")

if __name__ == "__main__":
    #ni = 4; no = 4; data = [i for i in range(1 << ni)] # 1:1 mapping (identity function)
    #ni = 4; no = 4; data = [15 - i for i in range(1 << ni)] # 1:15 mapping (inverse identity function)

    #ni = 4; no = 3; data = [bin(i).count('1') for i in range(1 << ni)] # Population Count (number of set bits)

    ni = 2; no = 8; data = [0, 255, 128, 64]
    # "Interesting" mapping: Population Count (number of set bits)
    print(data)
    generate_lut(ni, no, data, "lut")

