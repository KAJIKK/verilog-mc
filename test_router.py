import mcschematic
import shutil
import os
import sys
from collections import Counter

# Add current directory to path
sys.path.append(os.path.dirname(__file__))

from router import route

def test_router():
    print("=== Router Stress Test ===")
    
    # 1. Define Nets (Multi-pin support)
    # Format: [(x, y, is_top), ...]
    nets = [
        # NET 1: Straight (X=0 Top to X=0 Bot)
        [(0, 0, True), (0, 0, False)],
        
        # NET 2: Short Span (X=4 Top to X=2 Bot)
        [(4, 0, True), (2, 0, False)],
        
        # NET 3: Feedback Loop (X=12 Bot to X=6 Top)
        [(6, 0, True), (12, 0, False)],
        
        # NET 4: Top-to-Top connection (Bussing)
        [(10, 0, True), (8, 0, True)], 
        
        # ACTUAL STRESS TEST NETS FOR VCG/CYCLES:
        [(22, 0, True), (20, 0, False)],                 # Net 5: (T=22, B=20)
        [(20, 0, True), (22, 0, False)],                 # Net 6: (T=20, B=22) -> Cycle!
        
        # NET 7: Multi-pin Mixed (Top heavy)
        [(14, 0, True), (16, 0, True), (14, 0, False)], # Net 7: (T=14, T=16, B=14)
        
        # NET 8: Multi-pin Mixed (Bot heavy)
        [(24, 0, False), (26, 0, False), (24, 0, True)] # Net 8: (B=24, B=26, T=24)
    ]
    
    # 2. Define Dummy Gates
    class DummyGate:
        def __init__(self, x, width):
            self.x_offset = x
            self.size_x = width
            
    # Leave gaps for doglegs (Even Xs: 22, 24, etc.)
    top_gates = [DummyGate(x, 1) for x in range(0, 27) if x not in [22, 24]]
    bot_gates = [DummyGate(x, 1) for x in range(0, 27) if x not in [22, 24]]
    
    # 3. Run Router
    print("Routing...")
    circuit = route(nets)#, top_gates, bot_gates)
    
    # 4. Analyze Results
    blocks_count = Counter(circuit.blocks.values())
    
    print("\nRouting Statistics:")
    print(f" - Total Blocks: {len(circuit.blocks)}")
    print(f" - Tracks Generated: {max(0, (circuit.size_z - 1) // 2)}")
    print(f" - Bridges (Light Gray Wool): {blocks_count.get('minecraft:light_gray_wool', 0)}")
    print(f" - Doglegs (Yellow Wool): {blocks_count.get('minecraft:yellow_wool', 0)}")
    
    # 5. Create Schematic
    schem = mcschematic.MCSchematic()
    
    width = circuit.size_x
    length = circuit.size_z
    
    for x in range(-2, width + 4):
        for z in range(-1, length + 1):
            schem.setBlock((x, 0, z), "minecraft:stone_bricks")
            
    # Mark all pin locations and add signs
    for i, pin_list in enumerate(nets):
        for px, py, is_top in pin_list:
            z_coord = 0 if is_top else length - 1
            z_sign = -1 if is_top else length
            rot = 8 if is_top else 0
            
            schem.setBlock((px, 0, z_coord), "minecraft:red_wool")
            
            # Sign info: Line 3 shows all pins (I=Top, O=Bot)
            net_parts = []
            for px_n, py_n, is_top_n in pin_list:
                prefix = "I" if is_top_n else "O"
                net_parts.append(f"{prefix}{px_n}")
            net_str = ",".join(net_parts)
            
            sign_nbt = f"{{front_text:{{messages:['X={px}','Net:{i+1}','{net_str}','']}}}}"
            schem.setBlock((px, 1, z_sign), f"minecraft:oak_sign[rotation={rot}]{sign_nbt}")
            
    # Place routed blocks at y=1
    for (x, y, z), block in circuit.blocks.items():
        schem.setBlock((x, y + 1, z), block)
        
    filename = "router_stress_test_multi"
    schem.save(".", filename, mcschematic.Version.JE_1_21_4)
    print(f"\nSaved {filename}.schem")
    
    target_dir = "/home/kajat/.local/share/PrismLauncher/instances/Fabulously Optimized(1)/minecraft/config/worldedit/schematics"
    os.makedirs(target_dir, exist_ok=True)
    shutil.copy2(f"{filename}.schem", os.path.join(target_dir, f"{filename}.schem"))
    print(f"Copied to {target_dir}")

if __name__ == "__main__":
    test_router()
