"""Exhaustive parallel Minecraft truth tests for hybrid primitive blueprints."""
import argparse
import json
from pathlib import Path

from logic_gates import LogicGates
from tests.generate_adder_test import fill_commands
from tests.live_test_runtime import install_chunk_lease


def primitive_cases():
    result = []
    for n in range(2,5):
        for pattern in range(1<<n):
            for invert in (0,1):
                result.append((f'minterm_{n}_{pattern}_{invert}',LogicGates.minterm_gate(n,pattern,invert),
                               lambda a,n=n,p=pattern,inv=invert:int((a & ((1<<n)-1)) == p)^inv))
    for kind in ('AND','NAND','OR','NOR'):
        factory = getattr(LogicGates,kind.lower()+'_gate')
        for n in range(1,5):
            gate = factory(n)
            def truth(a,n=n,kind=kind):
                bits = [(a>>i)&1 for i in range(n)]
                value = all(bits) if kind in ('AND','NAND') else any(bits)
                return int(value ^ (kind in ('NAND','NOR')))
            result.append((f'{kind.lower()}_{n}',gate,truth))
    result += [('not',LogicGates._not(),lambda a:int(not(a&1))),
               ('xor',LogicGates.xor_gate(),lambda a:(a&1)^((a>>1)&1)),
               ('xnor',LogicGates.xnor_gate(),lambda a:1^((a&1)^((a>>1)&1))),
               # Named MUX physical order is S,A,B.
               ('mux',LogicGates.mux_gate(),lambda a:((a>>2)&1) if a&1 else ((a>>1)&1))]
    return result


def generate(destination,origin=(-1390,-60,200),namespace='hybrid_prims'):
    cases = primitive_cases()
    root = destination/namespace
    functions = root/'data'/namespace/'function'
    functions.mkdir(parents=True,exist_ok=True)
    (root/'pack.mcmeta').write_text(json.dumps({'pack':{'description':'Parallel hybrid gate truth tables',
                         'min_format':[121,0],'max_format':[121,0]}})+'\n')
    def write(name,commands):
        (functions/f'{name}.mcfunction').write_text('\n'.join(commands)+'\n')
    fixtures,placement = [],[]
    low = origin[0],origin[1]-1,origin[2]
    high = origin[0]+95,origin[1]+7,origin[2]+((len(cases)+7)//8)*12-1
    for fragile in ('redstone_wire','redstone_torch','redstone_wall_torch','repeater','comparator'):
        placement += fill_commands(low,high,(0,0,0),f'minecraft:air replace minecraft:{fragile}')
    placement += fill_commands(low,high,(0,0,0))
    placement += fill_commands(low,(high[0],low[1],high[2]),(0,0,0),'minecraft:stone_bricks')
    for index,(name,gate,truth) in enumerate(cases):
        offset = origin[0]+(index%8)*12,origin[1],origin[2]+(index//8)*12+2
        def pos(p):
            return ' '.join(str(a+b) for a,b in zip(p,offset))
        blocks = dict(gate.blocks)
        drivers = []
        for x,y in gate.pin_positions(False):
            blocks[x,y,-1] = 'minecraft:repeater[facing=north]'
            blocks[x,y-1,-1] = 'minecraft:white_wool'
            drivers.append(pos((x,y,-2)))
        x,y = gate.pin_positions(True)[0]
        lamp = pos((x,y,gate.size_z))
        blocks[x,y,gate.size_z] = 'minecraft:redstone_lamp'
        for p,state in sorted(blocks.items(),key=lambda item:(
                2 if 'redstone_wire' in item[1] else 1 if any(s in item[1] for s in ('repeater','torch','comparator')) else 0,
                -item[0][1])):
            placement.append(f'setblock {pos(p)} {state}')
        fixtures.append(dict(name=name,drivers=drivers,lamp=lamp,truth=truth,origin=offset))
    chunks = install_chunk_lease(write,namespace,low,high)
    write('place',[f'function {namespace}:load']+placement+[f'data modify storage {namespace}:placement status set value "complete"'])
    write('start',[f'function {namespace}:load',f'scoreboard objectives add {namespace} dummy',
                   f'scoreboard players set #passed {namespace} 0',f'scoreboard players set #failed {namespace} 0',
                   f'data merge storage {namespace}:results {{status:"running",failures:[]}}',
                   f'function {namespace}:apply_0'])
    for step in range(32):
        address = step if step < 16 else 31-step
        apply,check = [],[]
        for f in fixtures:
            apply += [f'setblock {p} '+('minecraft:redstone_block' if (address>>i)&1 else 'minecraft:air')
                      for i,p in enumerate(f['drivers'])]
            condition = f'block {f["lamp"]} minecraft:redstone_lamp[lit={str(bool(f["truth"](address))).lower()}]'
            failure = json.dumps(dict(name=f['name'],address=address,step=step))
            check += [f'execute if {condition} run scoreboard players add #passed {namespace} 1',
                      f'execute unless {condition} run scoreboard players add #failed {namespace} 1',
                      f'execute unless {condition} run data modify storage {namespace}:results failures append value {failure}']
        write(f'apply_{step}',apply+[f'schedule function {namespace}:check_{step} 24t replace'])
        write(f'check_{step}',check+[f'function {namespace}:apply_{step+1}' if step < 31 else f'function {namespace}:finish'])
    write('finish',[f'data modify storage {namespace}:results status set value "complete"',
                    f'execute store result storage {namespace}:results passed int 1 run scoreboard players get #passed {namespace}',
                    f'execute store result storage {namespace}:results failed int 1 run scoreboard players get #failed {namespace}',
                    f'function {namespace}:unload'])
    write('stop',[f'schedule clear {namespace}:check_{i}' for i in range(32)]+[f'function {namespace}:unload'])
    manifest = dict(origin=origin,bounds=[low,high],circuits=len(fixtures),checks=32*len(fixtures),
                    settle_ticks=24,sprint_ticks=1000,leased_chunks=chunks,
                    fixtures=[{k:v for k,v in f.items() if k != 'truth'} for f in fixtures])
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k != 'fixtures'},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('datapacks',type=Path)
    parser.add_argument('--origin',type=int,nargs=3,default=(-1390,-60,200))
    args = parser.parse_args()
    generate(args.datapacks,tuple(args.origin))
