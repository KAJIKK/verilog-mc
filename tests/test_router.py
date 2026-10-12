import mcschematic
import shutil
import os
import sys
from collections import Counter

# Add current directory to path
sys.path.append(os.path.dirname(__file__))

from router import route

def verify_circuit_connectivity(circuit, nets):
    print("Verifying circuit connectivity...")
    length = circuit.size_z
    pin_to_net = {}
    for net_idx, pin_list in enumerate(nets):
        for px, py, is_top in pin_list:
            z_coord = 0 if is_top else length - 1
            pin_coord = (px, 0, z_coord)
            pin_to_net[pin_coord] = net_idx

    for net_idx, pin_list in enumerate(nets):
        for pin in pin_list:
            px, py, is_top = pin
            z_coord = 0 if is_top else length - 1
            start_coord = (px, 0, z_coord)
            
            if start_coord not in circuit.blocks:
                raise ValueError(f"MISSING PIN: Net {net_idx + 1} pin {pin} at {start_coord} has no block placed in circuit.")
            
            block = circuit.blocks[start_coord]
            if block != "minecraft:redstone_wire":
                raise ValueError(f"INVALID PIN BLOCK: Net {net_idx + 1} pin {pin} at {start_coord} is not redstone wire (got '{block}').")

            # BFS traversal to find all connected redstone wire blocks in 3D
            visited = set()
            queue = [start_coord]
            visited.add(start_coord)
            
            while queue:
                curr = queue.pop(0)
                x, y, z = curr
                
                # Check if we reached a pin of a different net
                if curr in pin_to_net and pin_to_net[curr] != net_idx:
                    raise ValueError(
                        f"SHORT DETECTED: Net {net_idx + 1} (starting pin {pin}) "
                        f"is shorted to Net {pin_to_net[curr] + 1} at pin coordinate {curr}!"
                    )
                
                # Check 4 horizontal directions (dx, dz)
                for dx, dz in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                    # 1. Same-level connection
                    npos_same = (x + dx, y, z + dz)
                    if circuit.blocks.get(npos_same) == "minecraft:redstone_wire":
                        if npos_same not in visited:
                            visited.add(npos_same)
                            queue.append(npos_same)
                    
                    # 2. Climbing connection
                    npos_up = (x + dx, y + 1, z + dz)
                    if circuit.blocks.get(npos_up) == "minecraft:redstone_wire":
                        # Check throat block at (x, y + 1, z)
                        throat = circuit.blocks.get((x, y + 1, z))
                        if throat is None or "wool" not in throat:
                            if npos_up not in visited:
                                visited.add(npos_up)
                                queue.append(npos_up)
                    
                    # 3. Descending connection
                    npos_down = (x + dx, y - 1, z + dz)
                    if circuit.blocks.get(npos_down) == "minecraft:redstone_wire":
                        # Check throat block at (x + dx, y, z + dz)
                        throat = circuit.blocks.get((x + dx, y, z + dz))
                        if throat is None or "wool" not in throat:
                            if npos_down not in visited:
                                visited.add(npos_down)
                                queue.append(npos_down)
            
            # Check if all pins of the same net were visited
            for other_pin in pin_list:
                ox, oy, o_is_top = other_pin
                oz = 0 if o_is_top else length - 1
                other_coord = (ox, 0, oz)
                if other_coord not in visited:
                    raise ValueError(
                        f"MISSING CONNECTION: Net {net_idx + 1} pin {other_pin} is not connected "
                        f"to starting pin {pin}!"
                    )
            
            print(f"  Net {net_idx + 1} (pin {pin}): Traversed {len(visited)} connected redstone wire blocks successfully.")
    print("Connectivity verification passed! No shorts or missing connections detected.")


def test_router():
    print("=== Router Stress Test ===")
    
    # 1. Define Nets (Multi-pin support)
    # Format: [(x, y, is_top), ...]
    nets = [
        # NET 1: Straight (X=0 Top to X=0 Bot)
        [(0, 0, True), (0, 0, False)],
        
        # NET 2: Short Span (X=4 Top to X=2 Bot)
        [(4, 2, True), (2, 0, False)],
        
        # NET 3: Feedback Loop (X=12 Bot to X=6 Top)
        [(6, 0, True), (12, 4, False)],
        
        # NET 4: Top-to-Top connection (Bussing)
        [(10, 0, True), (8, 0, True)], 
        
        # ACTUAL STRESS TEST NETS FOR VCG/CYCLES:
        [(22, 0, True), (20, 0, False)],                 # Net 5: (T=22, B=20)
        [(20, 0, True), (22, 0, False)],                 # Net 6: (T=20, B=22) -> Cycle!
        
        # NET 7: Multi-pin Mixed (Top heavy)
        [(14, 0, True), (16, 0, True), (14, 6, False)], # Net 7: (T=14, T=16, B=14)
        
        # NET 8: Multi-pin Mixed (Bot heavy)
        [(24, 0, False), (26, 0, False), (24, 0, True)], # Net 8: (B=24, B=26, T=24)

        # --- NEW HARDER STRESS TEST CASES ---
        
        # NET 9: 3-way Vertical Cycle (Net 9, 10, 11) at X=28, 30, 32
        [(30, 0, True), (28, 0, False)],                 # Net 9: (T=30, B=28)
        [(28, 0, True), (32, 0, False)],                 # Net 10: (T=28, B=32)
        [(32, 0, True), (30, 0, False)],                 # Net 11: (T=32, B=30) -> 3-way cycle!

        # NET 12 & 13: Interlocking Multi-pin Bus
        [(34, 0, True), (36, 0, False), (38, 0, True), (40, 0, False)], # Net 12: 4 pins
        [(36, 0, True), (34, 0, False), (40, 0, True), (38, 0, False)], # Net 13: 4 pins, interlocking!

        # NET 14: Long range crossing feed
        [(2, 0, True), (42, 0, False)],                  # Net 14: (T=2, B=42) - massive length crosser

        # NET 15: Intermediate straight crossing cycle column
        [(18, 0, True), (18, 0, False)]                  # Net 15: Straight run in the middle
    ]
    
    # 2. Define Dummy Gates
    class DummyGate:
        def __init__(self, x, width):
            self.x_offset = x
            self.size_x = width
            
    # Leave gaps for cycles and multi-pin channels (Even Xs: 22, 24, 28, 30, 32, 34, 36, 38, 40)
    top_gates = [DummyGate(x, 1) for x in range(0, 43) if x not in [22, 24, 28, 30, 32, 34, 36, 38, 40]]
    bot_gates = [DummyGate(x, 1) for x in range(0, 43) if x not in [22, 24, 28, 30, 32, 34, 36, 38, 40]]
    
    # 3. Run Router
    print("Routing...")
    circuit = route(nets, warn_overwrite=True)
    
    # Verify circuit connectivity/shorts using Minecraft redstone wiring traversal rules
    verify_circuit_connectivity(circuit, nets)
    
    # 4. Analyze Results
    blocks_count = Counter(circuit.blocks.values())
    
    print("\nRouting Statistics:")
    print(f" - Total Blocks: {len(circuit.blocks)}")
    print(f" - Tracks Generated: {max(0, (circuit.size_z - 1) // 2)}")
    print(f" - Bridges (Light Gray Wool): {blocks_count.get('minecraft:light_gray_wool', 0)}")
    print(f" - Doglegs (Yellow Wool): {blocks_count.get('minecraft:yellow_wool', 0)}")
    
    # 5. Create Schematic
    schem = mcschematic.MCSchematic()
    
    # Calculate bounding box of all occupied elements (blocks + pins + signs)
    length = circuit.size_z
    min_x = min(x for (x, y, z) in circuit.blocks.keys()) if circuit.blocks else 0
    max_x = max(x for (x, y, z) in circuit.blocks.keys()) if circuit.blocks else 0
    for pin_list in nets:
        for px, py, is_top in pin_list:
            min_x = min(min_x, px)
            max_x = max(max_x, px)
            
    # Platform spans from min_x - 1 to max_x + 1 horizontally, and z from -1 to length
    for z in range(-1, length + 1):
        for x in range(min_x - 1, max_x + 2):
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
