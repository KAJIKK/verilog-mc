"""Exhaustive live primitive tests for zero through four inputs, eight outputs."""
import argparse
import json
from pathlib import Path
import mcschematic
from generate_lut import build_lut
from tests.generate_adder_test import placement_commands,fill_commands
from tests.live_test_runtime import install_chunk_lease


def generate(destination,origin):
    root = Path(destination)/'lut_test'
    functions = root/'data'/'lut_test'/'function'
    functions.mkdir(parents=True,exist_ok=True)
    (root/'pack.mcmeta').write_text(json.dumps({'pack':{'description':'LUT truth/interface tests',
        'min_format':[121,0],'max_format':[121,0]}},indent=2)+'\n')
    def write(name,commands):
        (functions/f'{name}.mcfunction').write_text('\n'.join(commands)+'\n')
    cases = []
    for n in range(5):
        data = [((a*73)^0xa5)&255 for a in range(1<<n)]
        if n == 2:
            data = [0,255,128,64]
        gate = build_lut(n,8,data)
        structure = mcschematic.MCSchematic()
        for z in range(-4,gate.size_z+2):
            for x in range(-1,gate.size_x+1):
                structure.setBlock((x,-1,z),'minecraft:stone_bricks')
        for pos,block in gate.blocks.items():
            structure.setBlock(pos,block)
        for j in range(n):
            x = 2*j+1
            structure.setBlock((x,5,-2),'minecraft:white_wool')
            structure.setBlock((x,4,-1),'minecraft:white_wool')
            structure.setBlock((x,5,-1),'minecraft:redstone_wire')
        for m in range(8):
            structure.setBlock((2*m,1,gate.size_z),'minecraft:redstone_lamp')
        # Same fixture area is reused, clearing the largest prior shape.
        write(f'place_{n}',fill_commands((-1,-1,-4),(16,6,36),origin)+placement_commands(structure.getStructure(),origin))
        for address in list(range(1<<n))+list(reversed(range(1<<n))):
            cases.append((n,address,data[address],gate.size_z))
    install_chunk_lease(write,'lut_test',(origin[0]-1,origin[1]-1,origin[2]-4),
                        (origin[0]+16,origin[1]+6,origin[2]+36))
    write('start',[f'schedule clear lut_test:check_{i}' for i in range(len(cases))]+['function lut_test:load','scoreboard objectives add lut_test dummy',
                   'scoreboard players set #passed lut_test 0','scoreboard players set #failed lut_test 0',
                   'data modify storage lut_test:results failures set value []',
                   'data modify storage lut_test:results status set value "running"','function lut_test:apply_0'])
    previous_n = None
    for i,(n,address,value,depth) in enumerate(cases):
        commands = []
        if n != previous_n:
            commands.append(f'function lut_test:place_{n}')
        commands += [f'scoreboard players set #case lut_test {i}',f'scoreboard players set #expected lut_test {value}',
                     f'scoreboard players set #width lut_test {n}',f'scoreboard players set #address lut_test {address}']
        for j in range(n):
            x,y,z = origin[0]+2*j+1,origin[1]+5,origin[2]
            commands += [f'setblock {x} {y} {z-3} minecraft:lever[face=wall,facing=north,powered={str(bool(address & (1<<j))).lower()}]',
                         f'setblock {x} {y} {z-1} minecraft:air',f'setblock {x} {y} {z-1} minecraft:redstone_wire']
        commands.append(f'schedule function lut_test:check_{i} 80t replace')
        write(f'apply_{i}',commands)
        check = ['scoreboard players set #actual lut_test 0']
        for m in range(8):
            x,y,z = origin[0]+2*m,origin[1]+1,origin[2]+depth
            check.append(f'execute if block {x} {y} {z} minecraft:redstone_lamp[lit=true] run scoreboard players add #actual lut_test {1<<m}')
        check += ['execute if score #actual lut_test = #expected lut_test run scoreboard players add #passed lut_test 1',
                  'execute unless score #actual lut_test = #expected lut_test run function lut_test:fail',
                  f'function lut_test:{"apply_"+str(i+1) if i+1 < len(cases) else "finish"}']
        write(f'check_{i}',check)
        previous_n = n
    write('fail',['scoreboard players add #failed lut_test 1','data modify storage lut_test:results failures append value {}']+
          [f'execute store result storage lut_test:results failures[-1].{name} int 1 run scoreboard players get #{name} lut_test'
           for name in ('case','width','address','expected','actual')])
    write('finish',['data modify storage lut_test:results status set value "complete"','function lut_test:unload']+
          [f'execute store result storage lut_test:results {name} int 1 run scoreboard players get #{name} lut_test' for name in ('passed','failed')])
    print(f'{len(cases)} exhaustive forward/reverse address checks; tick sprint {len(cases)*80+200}t')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('datapacks',type=Path)
    p.add_argument('--origin',nargs=3,type=int,required=True)
    args = p.parse_args()
    generate(args.datapacks,args.origin)
