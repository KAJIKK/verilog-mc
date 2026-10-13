import mcschematic
import os
import shutil
from numbers import Integral
from logic_gates import Gate

def build_lut(num_inputs, num_outputs, lut_data):
    """Build an in-memory gate; address bit j and output bit m retain order.

    The original decoder/encoder is unchanged. Boundary repeaters buffer the
    address bus and output bus for composition with other gates and routing.
    """
    # 0. Limits and Validation
    if isinstance(num_inputs,bool) or not isinstance(num_inputs,Integral) or not 0 <= num_inputs <= 4:
        raise ValueError(f"Too many inputs: {num_inputs} (max 4)")
    if isinstance(num_outputs,bool) or not isinstance(num_outputs,Integral) or not 1 <= num_outputs <= 8:
        raise ValueError(f"Too many outputs: {num_outputs} (max 8)")
    num_inputs,num_outputs = int(num_inputs),int(num_outputs)
    if len(lut_data) != (1 << num_inputs):
        raise ValueError(f"Data length mismatch: expected {1 << num_inputs}, got {len(lut_data)}")
    for val in lut_data:
        if not isinstance(val,Integral) or val < 0 or val >= (1 << num_outputs):
            raise ValueError(f"Data value {val} out of range for {num_outputs} outputs")
    lut_data = tuple(int(val) for val in lut_data)

    width = 2 * max(num_inputs, num_outputs)
    gate = Gate(width, 6, 2*(1 << num_inputs)+2, num_inputs, num_outputs)
    gate.input_offsets = {f'I{j}':[2*j+1,5] for j in range(num_inputs)}
    gate.output_offsets = {f'O{m}':[2*m,1] for m in range(num_outputs)}
    def place(position,block):
        gate.set_block(*position,block)
    
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
            place((x, 0, z), BLUE)
            if z % 16 == 1 and z != 1:  # Place a repeater every 16 blocks for signal strength
                place((x, 1, z), f"{REPEATER}[facing=north]")
            else:
                place((x, 1, z), WIRE)
            
    # 2. White Wool (Rows)
    # Rows at z=1, 3, 5... (odd)
    # Each row is a full bar across the width
    for i in range(num_rows):
        z = 2 * i + 1
        for x in range(width):
            place((x, 2, z), WHITE)
            place((x, 3, z), WIRE)

        # Encoder Logic: Torches pull up Blue wire if bit is 1
        # Flip index because decoder has 0 at the back
        mapped_input = num_rows - 1 - i
        val = lut_data[mapped_input] if mapped_input < len(lut_data) else 0
        for m in range(num_outputs):
            if (val >> m) & 1 == 1:
                # Bit m maps to Column m at x = 2*m
                x_out = 2 * m
                place((x_out, 2, z + 1), f"{TORCH}[facing=south]")
            
    # 3. Red Wool (Decoder & Address)

    # Address lines at x=1, 3, 5, 7... at y=4
    for n in range(num_inputs):
        x = 2 * n + 1
        for z in range(1, num_rows * 2):
            place((x, 4, z), RED)
            place((x, 5, z), WIRE)
            
    # Decoder Logic at y=3, z=even
    # Bit 0 -> x=1, Bit 1 -> x=3, Bit 2 -> x=5, Bit 3 -> x=7
    # mapping: Bit j -> x = 2 * j + 1
    for i in range(num_rows):
        z = 2 * i
        for j in range(num_inputs):
            x = 2 * j + 1
            if (i >> j) & 1:
                place((x, 3, z), RED)
                place((x, 4, z), f"{REPEATER}[facing=north]")  # Repeater for bit=1
                place((x, 5, z), AIR)
            else:
                place((x-1, 4, z+1), f"{TORCH}[facing=west]")  # Torch for bit=0

    for j in range(num_inputs):
        place((2*j+1,4,0),RED)
        place((2*j+1,5,0),f'{REPEATER}[facing=north]')
    for m in range(num_outputs):
        place((2*m,0,2*num_rows+1),BLUE)
        place((2*m,1,2*num_rows+1),f'{REPEATER}[facing=north]')
    gate.lut_data = tuple(lut_data)
    return gate


def generate_lut(num_inputs, num_outputs, lut_data, filename="lut"):
    gate = build_lut(num_inputs,num_outputs,lut_data)
    schem = mcschematic.MCSchematic()
    for z in range(-1,gate.size_z+1):
        for x in range(-1,gate.size_x+1):
            schem.setBlock((x,-1,z),'minecraft:stone_bricks')
    for pos,block in gate.blocks.items():
        schem.setBlock(pos,block)
    print("Saving LUT schematic...")
    schem.save(".", filename, mcschematic.Version.JE_1_21_4)
    
    target_dir = os.environ.get('WORLDEDIT_SCHEMATICS_DIR',
        "/home/kajat/.local/share/PrismLauncher/instances/Fabulously Optimized/minecraft/config/worldedit/schematics")
    os.makedirs(target_dir, exist_ok=True)
    shutil.copy2(f"{filename}.schem", os.path.join(target_dir, f"{filename}.schem"))
    print(f"Copied {filename}.schem to {target_dir}")
    return gate

if __name__ == "__main__":
    #ni = 4; no = 4; data = [i for i in range(1 << ni)] # 1:1 mapping (identity function)
    #ni = 4; no = 4; data = [15 - i for i in range(1 << ni)] # 1:15 mapping (inverse identity function)

    #ni = 4; no = 3; data = [bin(i).count('1') for i in range(1 << ni)] # Population Count (number of set bits)

    ni = 2; no = 8; data = [0, 255, 128, 64]
    # "Interesting" mapping: Population Count (number of set bits)
    print(data)
    generate_lut(ni, no, data, "lut")
