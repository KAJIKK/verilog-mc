"""Import the user's SR and toggle/reset WorldEdit blueprints into gates.json."""
import argparse
import json
from pathlib import Path

from extract_gate import read_schem, normalize_block


def import_primitives(folder, library):
    data = json.loads(library.read_text())
    profiles = {
        'SR_LATCH': ('SR_latch_primitive.schem', {'S': 2, 'R': 0}, {'QN': 0, 'Q': 2}),
        'T_LATCH': ('T_latch_primitive.schem', {'R': 0, 'T': 2}, {'QN': 0, 'Q': 2}),
    }
    for name, (filename, inputs, outputs) in profiles.items():
        gate = read_schem(folder / filename)
        # Array coordinates start at the selection minimum, independent of
        # WorldEdit's clipboard/player offset. Observer is therefore (0,0,0).
        gate['blocks'] = {pos: normalize_block(block) for pos, block in gate['blocks'].items()}
        gate.update(num_inputs=len(inputs), num_outputs=len(outputs),
                    input_offsets=inputs, output_offsets=outputs)
        gate['behavior'] = ({'kind': 'sr_latch', 'active_high': True,
                             'simultaneous_set_reset': 'forbidden'} if name == 'SR_LATCH' else
                            {'kind': 'toggle_reset', 'toggle_edge': 'rising',
                             'reset_edge': 'both', 'reset_requires_toggle_low': True,
                             'tested_toggle_high_ticks': [4, 8, 20, 100, 1200],
                             'tested_toggle_low_ticks': 60,
                             'two_tick_toggle_supported': False})
        data[name] = gate
        print(f'{name}: {gate["size"]}, {len(gate["blocks"])} blocks, inputs={inputs}, outputs={outputs}')
    library.write_text(json.dumps(data, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('schematics', type=Path)
    parser.add_argument('--library', type=Path, default=Path('gates.json'))
    args = parser.parse_args()
    import_primitives(args.schematics, args.library)
