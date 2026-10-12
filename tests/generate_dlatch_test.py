"""Generate a Minecraft 26.3 datapack that tests real D-latch state over time."""
import argparse
import json
import random
from pathlib import Path

import mcschematic


def test_sequence():
    """Change one input at a time, allowing for physical propagation delays."""
    steps = [{"d": 0, "enable": 0, "label": "initial inputs"},
             {"enable": 1, "label": "initialize zero"}]
    for stored in (0, 1):
        for data in (0, 1):
            for enable in (0, 1):
                label = f"previous={stored},d={data},enable={enable}"
                steps.extend([
                    {"enable": 0, "label": f"{label}: close"},
                    {"d": stored, "label": f"{label}: setup stored value"},
                    {"enable": 1, "label": f"{label}: load stored value"},
                    {"enable": 0, "label": f"{label}: capture"},
                    {"d": data, "label": f"{label}: change data"},
                    {"enable": enable, "label": f"{label}: result"},
                ])
        steps.extend([
            {"enable": 0, "label": f"hold {stored}: close"},
            {"d": stored, "label": f"hold {stored}: setup"},
            {"enable": 1, "label": f"hold {stored}: load"},
            {"enable": 0, "label": f"hold {stored}: capture"},
            {"d": 1 - stored, "wait": 1200,
             "label": f"hold {stored} against opposite data for 1200 ticks"},
        ])
    rng = random.Random(2026)
    for i in range(128):
        port = rng.choice(("d", "enable"))
        steps.append({port: rng.randrange(2), "label": f"random transition {i}"})
    steps.extend([
        {"enable": 0, "label": "final demo: close"},
        {"d": 1, "label": "final demo: setup one"},
        {"enable": 1, "label": "final demo: load one"},
        {"enable": 0, "label": "final demo: capture one"},
        {"d": 0, "wait": 1200, "label": "final demo: retain one with data zero"},
    ])
    return steps


def generate(schematic, origin, destination):
    structure = mcschematic.MCSchematic(str(schematic)).getStructure()
    pins = {}
    storage_repeaters = []
    for pos in structure.getBlockStates():
        block = structure.getBlockDataAt(pos)
        if "oak_sign" in block:
            for port in ("d", "enable", "q"):
                if f'"{port}"' in block:
                    pins[port] = tuple(p + o - (axis == 1)
                                       for axis, (p, o) in enumerate(zip(pos, origin)))
        if "repeater" in block:
            x, y, z = pos
            side = structure.getBlockStateAt((x - 1, y, z))
            if "facing=north" in block and "repeater" in side and "facing=west" in side:
                storage_repeaters.append(tuple(p + o for p, o in zip(pos, origin)))
    if set(pins) != {"d", "enable", "q"} or len(storage_repeaters) != 1:
        raise ValueError("Expected d/enable/q labels and exactly one locked-repeater storage cell")

    root = Path(destination) / "dlatch_test"
    functions = root / "data" / "dlatch_test" / "function"
    functions.mkdir(parents=True, exist_ok=True)
    (root / "pack.mcmeta").write_text(json.dumps({"pack": {
        "description": "Live D-latch transparency and retention test",
        "min_format": [121, 0], "max_format": [121, 0]
    }}, indent=2) + "\n")

    def write(name, commands):
        (functions / f"{name}.mcfunction").write_text("\n".join(commands) + "\n")

    steps = test_sequence()
    write("start", [
        f"schedule clear dlatch_test:check_{i}" for i in range(len(steps))
    ] + [
        "scoreboard objectives add dlatch_test dummy",
        "scoreboard players set #passed dlatch_test 0",
        "scoreboard players set #failed dlatch_test 0",
        "data modify storage dlatch_test:results failures set value []",
        'data modify storage dlatch_test:results status set value "running"',
        "function dlatch_test:apply_0",
    ])

    values = {"d": 0, "enable": 0}
    q = None
    assertions = 0
    total_ticks = 0
    qpos = " ".join(map(str, pins["q"]))
    memorypos = " ".join(map(str, storage_repeaters[0]))
    for i, step in enumerate(steps):
        apply = []
        for port in ("d", "enable"):
            if port not in step:
                continue
            # Leave unchanged signals alone: refreshing data while closing
            # enable could otherwise introduce an artificial transient.
            if i != 0 and values[port] == step[port]:
                continue
            values[port] = step[port]
            x, y, z = pins[port]
            powered = str(bool(values[port])).lower()
            apply.extend([
                f"setblock {x} {y} {z-1} minecraft:lever[face=wall,facing=north,powered={powered}]",
                # Notify first dust after command placement of the lever.
                f"setblock {x} {y} {z+1} minecraft:air",
                f"setblock {x} {y} {z+1} minecraft:redstone_wire",
            ])
        if values["enable"]:
            q = values["d"]
        wait = step.get("wait", 60)
        total_ticks += wait
        apply.append(f"schedule function dlatch_test:check_{i} {wait}t replace")
        write(f"apply_{i}", apply)

        check = []
        if q is not None:
            assertions += 1
            check.extend([
                "scoreboard players set #ok dlatch_test 1",
                "scoreboard players set #actual dlatch_test 0",
                f"execute if block {qpos} minecraft:redstone_lamp[lit=true] run scoreboard players set #actual dlatch_test 1",
                f"execute unless score #actual dlatch_test matches {q} run scoreboard players set #ok dlatch_test 0",
                f"execute unless block {memorypos} minecraft:repeater[locked={str(not values['enable']).lower()},powered={str(bool(q)).lower()}] run scoreboard players set #ok dlatch_test 0",
            ])
            for port in ("d", "enable"):
                x, y, z = pins[port]
                check.append(f"execute unless block {x} {y} {z+1} minecraft:redstone_wire[power={15 * values[port]}] run scoreboard players set #ok dlatch_test 0")
            check.extend([
                "execute if score #ok dlatch_test matches 1 run scoreboard players add #passed dlatch_test 1",
                f"execute if score #ok dlatch_test matches 0 run function dlatch_test:fail_{i}",
            ])
            entry = {"step": i, "label": step["label"], "d": values["d"],
                     "enable": values["enable"], "expected": q, "actual": -1}
            # These entries use only integers and JSON strings, valid SNBT.
            write(f"fail_{i}", [
                "scoreboard players add #failed dlatch_test 1",
                f"data modify storage dlatch_test:results failures append value {json.dumps(entry)}",
                "execute store result storage dlatch_test:results failures[-1].actual int 1 run scoreboard players get #actual dlatch_test",
            ])
        check.append(f"function dlatch_test:apply_{i+1}" if i + 1 < len(steps)
                     else "function dlatch_test:finish")
        write(f"check_{i}", check)
    write("finish", [
        'data modify storage dlatch_test:results status set value "complete"',
        f"data modify storage dlatch_test:results total set value {assertions}",
        "execute store result storage dlatch_test:results passed int 1 run scoreboard players get #passed dlatch_test",
        "execute store result storage dlatch_test:results failed int 1 run scoreboard players get #failed dlatch_test",
        'tellraw @a [{"text":"D latch test complete. Passed: "},{"score":{"name":"#passed","objective":"dlatch_test"}},{"text":"; failed: "},{"score":{"name":"#failed","objective":"dlatch_test"}}]',
    ])
    print(json.dumps({"pack": str(root), "origin": origin, "pins": pins,
                      "storage_repeater": storage_repeaters[0], "assertions": assertions,
                      "ticks": total_ticks, "sprint_command": f"tick sprint {total_ticks + 200}t"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schematic", type=Path)
    parser.add_argument("datapacks", type=Path)
    parser.add_argument("--origin", type=int, nargs=3, required=True)
    args = parser.parse_args()
    generate(args.schematic, args.origin, args.datapacks)
