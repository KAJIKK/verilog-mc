import nbtlib
import sys
import json

def read_schem(filepath):
    nbt = nbtlib.load(filepath)
    schem = nbt.get('Schematic', nbt)
    width = int(schem['Width'])
    height = int(schem['Height'])
    length = int(schem['Length'])
    
    blocks_node = schem.get('Blocks', schem)
    palette = blocks_node['Palette']
    data = blocks_node.get('Data', blocks_node.get('BlockData'))
    # Sponge palette indexes are unsigned variable-length integers, not bytes.
    indexes = []
    value = shift = 0
    for byte in data:
        byte = int(byte) & 255
        value |= (byte & 127) << shift
        if byte & 128:
            shift += 7
        else:
            indexes.append(value)
            value = shift = 0
    if shift or len(indexes) != width * height * length:
        raise ValueError('Invalid schematic block data length')
    
    # Invert palette
    id_to_block = {int(v): str(k) for k, v in palette.items()}
    
    result_blocks = {}
    
    # Sponge format index: (y * length + z) * width + x
    for y in range(height):
        for z in range(length):
            for x in range(width):
                idx = (y * length + z) * width + x
                block_id = indexes[idx]
                block_name = id_to_block[block_id]
                
                if block_name.split('[')[0] in ('minecraft:air', 'minecraft:cave_air', 'minecraft:void_air', 'minecraft:stone_bricks'):
                    continue
                
                result_blocks[f"{x},{y},{z}"] = block_name

    return {
        "size": [width, height, length],
        "blocks": result_blocks
    }
    
def parse_schem(filepath):
    print(json.dumps(read_schem(filepath), indent=2))


def normalize_block(block):
    """Discard captured transient states; retain orientation and component mode."""
    name, _, state = block.partition('[')
    if not state:
        return name
    props = dict(prop.split('=') for prop in state.rstrip(']').split(','))
    for prop in ('powered', 'locked', 'power', 'lit'):
        props.pop(prop, None)
    if name == 'minecraft:redstone_wire':
        return name
    if name.endswith('copper_bulb'):
        props.update(lit='false', powered='false')
    return name + ('[' + ','.join(f'{k}={v}' for k, v in props.items()) + ']' if props else '')

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_gate.py <schem_file>")
    else:
        parse_schem(sys.argv[1])
