"""Generate an exhaustive in-world lamp test for the adder4 schematic.

Run with the WorldEdit paste origin and the world's datapacks directory, then
use /reload, /function adder4_test:start and /tick sprint 26000t via Minecraft MCP.
"""
import argparse
import json
import re
from pathlib import Path

import mcschematic


def fill_commands(low, high, origin, block='minecraft:air'):
    """Split all three axes so even a large floor fits the 32768-block cap."""
    def world_pos(p):
        return ' '.join(str(a+b) for a,b in zip(p,origin))
    dx = min(high[0]-low[0]+1,32768)
    dy = min(high[1]-low[1]+1,32768//dx)
    dz = min(high[2]-low[2]+1,32768//(dx*dy))
    return [f'fill {world_pos((x,y,z))} '
            f'{world_pos((min(x+dx-1,high[0]),min(y+dy-1,high[1]),min(z+dz-1,high[2])))} {block}'
            for x in range(low[0],high[0]+1,dx)
            for y in range(low[1],high[1]+1,dy)
            for z in range(low[2],high[2]+1,dz)]


def placement_commands(structure, origin):
    """Exact-origin placement shared by live tests, with supports before dust."""
    states = {p:structure.getBlockStateAt(p) for p in structure.getBlockStates()}
    low = tuple(min(p[axis] for p in states) for axis in range(3))
    high = tuple(max(p[axis] for p in states) for axis in range(3))
    def world_pos(p):
        return ' '.join(str(a+b) for a,b in zip(p,origin))
    placement = fill_commands(low,high,origin)
    def rank(item):
        state = item[1]
        return (2 if 'redstone_wire' in state else
                1 if any(name in state for name in ('repeater','comparator','torch','sign','lever')) else 0,
                -item[0][1],-item[0][2],item[0][0])
    for p,state in sorted(states.items(),key=rank):
        if state.split('[',1)[0] in ('minecraft:air','minecraft:cave_air','minecraft:void_air'):
            continue
        data = structure.getBlockDataAt(p) if 'sign' in state else ''
        placement.append(f'setblock {world_pos(p)} {data or state}')
    return placement


def generate(schematic, origin, destination, namespace='adder4_test'):
    if not re.fullmatch(r'[a-z0-9_]{1,16}',namespace):
        raise ValueError('Test namespace must be 1-16 lowercase letters, digits or underscores')
    structure = mcschematic.MCSchematic(str(schematic)).getStructure()
    pins = {}
    for pos in structure.getBlockStates():
        if "oak_sign" in structure.getBlockStateAt(pos):
            # The library labels each IO sign with its Verilog port and bit.
            data = structure.getBlockDataAt(pos)
            for port, width in (("a", 4), ("b", 4), ("sum", 5)):
                for bit in range(width):
                    if f'"{port}[{bit}]"' in data:
                        pins[f"{port}[{bit}]"] = tuple(
                            p + o - (1 if axis == 1 else 0)
                            for axis, (p, o) in enumerate(zip(pos, origin))
                        )
    if len(pins) != 13:
        raise ValueError(f"Expected 13 labeled IO pins, found {pins}")

    root = Path(destination) / namespace
    functions = root / "data" / namespace / "function"
    functions.mkdir(parents=True, exist_ok=True)
    (root / "pack.mcmeta").write_text(json.dumps({"pack": {
        "description": "Exhaustive live redstone adder4 test",
        "min_format": [121, 0], "max_format": [121, 0]
    }}, indent=2) + "\n")

    def write(name, commands):
        (functions / f"{name}.mcfunction").write_text(
            "\n".join(command.replace('adder4_test',namespace) for command in commands) + "\n")

    # Optional exact-origin placement, independent of the player's movement.
    # Existing WorldEdit workflows still call start after their own paste.
    write('place',placement_commands(structure,origin))

    write("start", [
        "schedule clear adder4_test:check",
        "scoreboard objectives add adder4_test dummy",
        "scoreboard players set #case adder4_test 0",
        "scoreboard players set #passed adder4_test 0",
        "scoreboard players set #failed adder4_test 0",
        "scoreboard players set #two adder4_test 2",
        "scoreboard players set #sixteen adder4_test 16",
        "data modify storage adder4_test:results failures set value []",
        "data modify storage adder4_test:results status set value \"running\"",
        "function adder4_test:apply",
    ])
    apply = [
        "scoreboard players operation #a adder4_test = #case adder4_test",
        "scoreboard players operation #a adder4_test %= #sixteen adder4_test",
        "scoreboard players operation #b adder4_test = #case adder4_test",
        "scoreboard players operation #b adder4_test /= #sixteen adder4_test",
        "scoreboard players operation #expected adder4_test = #a adder4_test",
        "scoreboard players operation #expected adder4_test += #b adder4_test",
    ]
    for port in ("a", "b"):
        apply.append(f"scoreboard players operation #bits adder4_test = #{port} adder4_test")
        for bit in range(4):
            x, y, z = pins[f"{port}[{bit}]"]
            apply.extend([
                "scoreboard players operation #bit adder4_test = #bits adder4_test",
                "scoreboard players operation #bit adder4_test %= #two adder4_test",
                f"execute if score #bit adder4_test matches 0 run setblock {x} {y} {z-1} minecraft:lever[face=wall,facing=north,powered=false]",
                f"execute if score #bit adder4_test matches 1 run setblock {x} {y} {z-1} minecraft:lever[face=wall,facing=north,powered=true]",
                "scoreboard players operation #bits adder4_test /= #two adder4_test",
                # /setblock on a lever doesn't perform the attached-block
                # neighbor notification that right-clicking the lever does.
                # Recreate the first dust to recalculate its input power.
                f"setblock {x} {y} {z+1} minecraft:air",
                f"setblock {x} {y} {z+1} minecraft:redstone_wire",
            ])
    apply.append("schedule function adder4_test:check 100t replace")
    write("apply", apply)
    check = ["scoreboard players set #actual adder4_test 0"]
    for bit in range(5):
        x, y, z = pins[f"sum[{bit}]"]
        check.append(f"execute if block {x} {y} {z} minecraft:redstone_lamp[lit=true] run scoreboard players add #actual adder4_test {1 << bit}")
    check.extend([
        "execute if score #actual adder4_test = #expected adder4_test run scoreboard players add #passed adder4_test 1",
        "execute unless score #actual adder4_test = #expected adder4_test run function adder4_test:fail",
        "scoreboard players add #case adder4_test 1",
        "execute if score #case adder4_test matches ..255 run function adder4_test:apply",
        "execute if score #case adder4_test matches 256 run function adder4_test:finish",
    ])
    write("check", check)
    fail = [
        "scoreboard players add #failed adder4_test 1",
        "data modify storage adder4_test:results failures append value {a:0,b:0,expected:0,actual:0}",
    ]
    for name in ("a", "b", "expected", "actual"):
        fail.append(f"execute store result storage adder4_test:results failures[-1].{name} int 1 run scoreboard players get #{name} adder4_test")
    write("fail", fail)
    write("finish", [
        "data modify storage adder4_test:results status set value \"complete\"",
        "execute store result storage adder4_test:results passed int 1 run scoreboard players get #passed adder4_test",
        "execute store result storage adder4_test:results failed int 1 run scoreboard players get #failed adder4_test",
        'tellraw @a [{"text":"Adder4 exhaustive test complete. Passed: "},{"score":{"name":"#passed","objective":"adder4_test"}},{"text":" / 256; failed: "},{"score":{"name":"#failed","objective":"adder4_test"}}]',
    ])
    print(json.dumps({"pack": str(root), "origin": origin, "pins": pins}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schematic", type=Path)
    parser.add_argument("datapacks", type=Path)
    parser.add_argument("--origin", type=int, nargs=3, required=True)
    parser.add_argument('--namespace',default='adder4_test',help='Separate datapack/storage name for experiments')
    args = parser.parse_args()
    generate(args.schematic, args.origin, args.datapacks,args.namespace)
