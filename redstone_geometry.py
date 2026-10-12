"""Electrical dust/repeater adjacency and power for the postprocessor."""
from collections import deque


HORIZONTAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
# Minecraft repeater facing points towards the input, opposite signal travel.
FACING = {(1, 0): 'west', (-1, 0): 'east', (0, 1): 'north', (0, -1): 'south'}


def signal_neighbors(position, signals, solids):
    """`signals`: coordinate -> None for dust or (dx,dz) for repeaters."""
    x, y, z = position
    direction = signals[position]
    if direction is not None:
        dx, dz = direction
        target = (x + dx, y, z + dz)
        if target in signals and signals[target] in (None, direction):
            yield target
        return
    for dx, dz in HORIZONTAL:
        for dy in (-1, 0, 1):
            target = (x + dx, y + dy, z + dz)
            if target not in signals:
                continue
            other = signals[target]
            if other is not None:
                if dy == 0 and other == (dx, dz):
                    yield target
            else:
                lower = position if dy == 1 else target
                throat = (lower[0], lower[1] + 1, lower[2])
                if dy == 0 or throat not in solids:
                    yield target


def signal_powers(signals, solids, source, source_power=15):
    """Steady-state power including directional repeater restoration."""
    powers = {source: source_power}
    queue = deque([source])
    while queue:
        pos = queue.popleft()
        for target in signal_neighbors(pos, signals, solids):
            if signals[pos] is not None or signals[target] is not None:
                power = 15 if powers[pos] > 0 else 0
            else:
                power = max(0, powers[pos] - 1)
            if power > powers.get(target, 0):
                powers[target] = power
                queue.append(target)
    return powers
