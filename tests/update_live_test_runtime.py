"""Upgrade existing generated ALU packs without rebuilding their geometry."""
import argparse
import json
from pathlib import Path
from tests.live_test_runtime import install_chunk_lease,install_case_dispatch


def upgrade(destination,namespace):
    root = Path(destination)/namespace
    manifest_path = root/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    functions = root/'data'/namespace/'function'
    def write(name,commands):
        (functions/f'{name}.mcfunction').write_text('\n'.join(commands)+'\n')
    manifest['leased_chunks'] = install_chunk_lease(write,namespace,*manifest['bounds'])
    write('stop',[f'schedule clear {namespace}:check',
                  f'data modify storage {namespace}:results status set value "stopped"',
                  f'function {namespace}:unload'])
    for name in ('place','start'):
        path = functions/f'{name}.mcfunction'
        lines = [line for line in path.read_text().splitlines() if not line.startswith('forceload add ')]
        load = f'function {namespace}:load'
        if load not in lines:
            lines.insert(0,load)
        if name == 'start':
            index = lines.index(f'function {namespace}:apply_0')
            for field in ('passed','failed','checked'):
                command = f'data modify storage {namespace}:results {field} set value 0'
                if command not in lines:
                    lines.insert(index,command)
                    index += 1
        write(name,lines)
    lines = (functions/'check.mcfunction').read_text().splitlines()
    lines = [line for line in lines
             if not line.startswith(f'execute if score #case {namespace} matches ')
             and not line.startswith(f'execute store result storage {namespace}:dispatch ')]
    for field in ('passed','failed'):
        command = f'execute store result storage {namespace}:results {field} int 1 run scoreboard players get #{field} {namespace}'
        if command not in lines:
            lines.append(command)
    write('check',lines+install_case_dispatch(write,namespace,manifest['cases']))
    lines = (functions/'finish.mcfunction').read_text().splitlines()
    unload = f'function {namespace}:unload'
    if unload not in lines:
        lines.append(unload)
    write('finish',lines)
    manifest.update(dispatch='macro',automatic_chunk_cleanup=True)
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Updated {namespace}: {manifest["leased_chunks"]} leased chunks, constant-size dispatch')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('datapacks',type=Path)
    parser.add_argument('--namespace',action='append',required=True)
    args = parser.parse_args()
    for namespace in args.namespace:
        upgrade(args.datapacks,namespace)
