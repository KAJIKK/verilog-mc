"""Reference-model and live lamp tests for alu8, including routing edge cases."""
import argparse
import json
from pathlib import Path
import random
import re

import mcschematic

from tests.generate_adder_test import placement_commands


def reference(a,b,op):
    if op == 0:
        result = a+b
    elif op == 1:
        # Extended two's-complement addition retains the no-borrow bit.
        result = a+(b ^ 255)+1
    elif op == 2:
        result = a ^ b
    else:
        result = a & b
    return result,int((result & 255) == 0)


def test_vectors():
    vectors = []
    def add(a,b,op,label):
        result,zero = reference(a,b,op)
        vectors.append({'a':a,'b':b,'op':op,'result':result,'zero':zero,'label':label})
    corners = (0,1,127,128,254,255,0x55,0xaa)
    for a in corners:
        for b in corners:
            for op in range(4):
                add(a,b,op,'corners/mode switching')
    for i in range(8):
        for a,b in ((1<<i,0),(0,1<<i),(1<<i,255),(255,1<<i)):
            for op in range(4):
                add(a,b,op,'walking bit/complement')
        for j in range(8):
            for op in range(4):
                add(1<<i,1<<j,op,'one-hot pair isolation')
    for width in range(1,9):
        mask = (1<<width)-1
        for a,b in ((mask,1),(1,mask),(0,mask),(mask,mask),(255,mask)):
            for op in range(4):
                add(a,b,op,'carry/borrow chain')
    rng = random.Random(20261013)
    for i in range(512):
        add(rng.randrange(256),rng.randrange(256),i%4,'random')
    for op in range(4):
        for a,b in ((255,255),(0,0),(255,0),(0,0)):
            add(a,b,op,'all-on/off recovery')
    return vectors


def verify_netlist(path,vectors):
    """Evaluate mapped Boolean cells independently of placement and Minecraft."""
    modules = json.loads(Path(path).read_text())['modules']
    module = modules['alu8']
    def is_output(cell,port):
        return cell.get('port_directions',{}).get(
            port,'output' if port in ('Y','Q','QN') else 'input') == 'output'
    drivers = {}
    for cell in module['cells'].values():
        for port,bits in cell['connections'].items():
            if is_output(cell,port):
                for bit in bits:
                    drivers[bit] = cell
    for vector in vectors:
        values = {'0':False,'1':True}
        for port in ('a','b','op'):
            values.update({bit:bool(vector[port] & (1<<i))
                           for i,bit in enumerate(module['ports'][port]['bits'])})
        active = set()
        def bit_value(bit):
            if bit in values:
                return values[bit]
            if bit in active:
                raise ValueError('Combinational loop in the mapped ALU')
            active.add(bit)
            cell = drivers[bit]
            if cell['type'] in ('$lut','$_LUT_','MC_LUT'):
                from lut_mapping import parameter_int
                address = sum(int(bit_value(b))<<i for i,b in enumerate(cell['connections']['A']))
                count = parameter_int(cell['parameters'].get('OUTPUTS',1))
                table = parameter_int(cell['parameters']['LUT'])
                output = cell['connections']['Y'].index(bit)
                values[bit] = bool((table>>(address*count+output))&1)
                active.remove(bit)
                return values[bit]
            args = {port:bit_value(bits[0]) for port,bits in cell['connections'].items()
                    if not is_output(cell,port)}
            a,b = args.get('A',False),args.get('B',False)
            kind = cell['type'].upper().replace('$','').strip('_').removesuffix('2')
            functions = {'BUF':lambda:a,'NOT':lambda:not a,'AND':lambda:a and b,
                         'NAND':lambda:not(a and b),'OR':lambda:a or b,
                         'NOR':lambda:not(a or b),'XOR':lambda:a != b,
                         'XNOR':lambda:a == b,'MUX':lambda:b if args['S'] else a}
            values[bit] = bool(functions[kind]())
            active.remove(bit)
            return values[bit]
        result = sum(int(bit_value(bit))<<i for i,bit in enumerate(module['ports']['result']['bits']))
        zero = int(bit_value(module['ports']['zero']['bits'][0]))
        if (result,zero) != (vector['result'],vector['zero']):
            raise ValueError(f'Netlist/reference mismatch: {vector}, actual {(result,zero)}')
    return len(vectors)


def generate(schematic,origin,destination,settle=400,namespace='alu8_test'):
    if not re.fullmatch(r'[a-z0-9_]{1,16}',namespace):
        raise ValueError('Test namespace must be 1-16 lowercase letters, digits or underscores')
    if settle < 1:
        raise ValueError('settle must be positive')
    structure = mcschematic.MCSchematic(str(schematic)).getStructure()
    pins = {}
    ports = [('a',8),('b',8),('op',2),('result',9),('zero',1)]
    for pos in structure.getBlockStates():
        if 'oak_sign' not in structure.getBlockStateAt(pos):
            continue
        data = structure.getBlockDataAt(pos)
        for port,width in ports:
            for i in range(width):
                name = port if width == 1 else f'{port}[{i}]'
                if f'"{name}"' in data:
                    pins[name] = tuple(p+o-(axis == 1) for axis,(p,o) in enumerate(zip(pos,origin)))
    if len(pins) != 28:
        raise ValueError(f'Expected 28 IO labels, found {pins}')
    vectors = test_vectors()
    root = Path(destination)/namespace
    functions = root/'data'/namespace/'function'
    functions.mkdir(parents=True,exist_ok=True)
    (root/'pack.mcmeta').write_text(json.dumps({'pack':{
        'description':'8-bit ALU carry, fan-out, reconvergence and isolation tests',
        'min_format':[121,0],'max_format':[121,0]}},indent=2)+'\n')
    def write(name,commands):
        (functions/f'{name}.mcfunction').write_text(
            '\n'.join(command.replace('alu8_test',namespace) for command in commands)+'\n')
    low = tuple(min(p[axis] for p in structure.getBlockStates())+origin[axis] for axis in range(3))
    high = tuple(max(p[axis] for p in structure.getBlockStates())+origin[axis] for axis in range(3))
    first_x,last_x = low[0]//16,high[0]//16
    first_z,last_z = low[2]//16,high[2]//16
    chunk_rows = max(1,256//(last_x-first_x+1))
    loads = [f'forceload add {low[0]} {z*16} {high[0]} {min(z+chunk_rows-1,last_z)*16}'
             for z in range(first_z,last_z+1,chunk_rows)]
    placement = placement_commands(structure,origin)
    batches = [placement[i:i+10000] for i in range(0,len(placement),10000)]
    write('place',[f'schedule clear alu8_test:place_{i}' for i in range(len(batches))]+
          loads+['data modify storage alu8_test:placement status set value "placing"',
                 'function alu8_test:place_0'])
    for i,batch in enumerate(batches):
        following = ([f'schedule function alu8_test:place_{i+1} 1t replace']
                     if i+1 < len(batches) else
                     ['data modify storage alu8_test:placement status set value "complete"',
                      'tellraw @a {"text":"ALU8 placement complete"}'])
        write(f'place_{i}',batch+following)
    write('start',['schedule clear alu8_test:check','scoreboard objectives add alu8_test dummy',
                   'scoreboard players set #passed alu8_test 0','scoreboard players set #failed alu8_test 0',
                   'data modify storage alu8_test:results failures set value []',
                   'data modify storage alu8_test:results status set value "running"',
                   'function alu8_test:apply_0'])
    previous = None
    for i,vector in enumerate(vectors):
        apply = [f'scoreboard players set #{name} alu8_test {vector[name]}'
                 for name in ('a','b','op','result','zero')]
        apply += [f'scoreboard players set #case alu8_test {i}']
        for port,width in ports[:3]:
            for bit in range(width):
                on = bool(vector[port] & (1<<bit))
                if previous is not None and on == bool(previous[port] & (1<<bit)):
                    continue
                x,y,z = pins[f'{port}[{bit}]']
                apply.extend([f'setblock {x} {y} {z-1} minecraft:lever[face=wall,facing=north,powered={str(on).lower()}]',
                              f'setblock {x} {y} {z+1} minecraft:air',
                              f'setblock {x} {y} {z+1} minecraft:redstone_wire'])
        apply.append(f'schedule function alu8_test:check {settle}t replace')
        write(f'apply_{i}',apply)
        previous = vector
    checks = ['scoreboard players set #actual alu8_test 0','scoreboard players set #actual_zero alu8_test 0']
    for bit in range(9):
        x,y,z = pins[f'result[{bit}]']
        checks.append(f'execute if block {x} {y} {z} minecraft:redstone_lamp[lit=true] run scoreboard players add #actual alu8_test {1<<bit}')
    x,y,z = pins['zero']
    checks.append(f'execute if block {x} {y} {z} minecraft:redstone_lamp[lit=true] run scoreboard players set #actual_zero alu8_test 1')
    checks += ['scoreboard players set #ok alu8_test 1',
               'execute unless score #actual alu8_test = #result alu8_test run scoreboard players set #ok alu8_test 0',
               'execute unless score #actual_zero alu8_test = #zero alu8_test run scoreboard players set #ok alu8_test 0',
               'execute if score #ok alu8_test matches 1 run scoreboard players add #passed alu8_test 1',
               'execute if score #ok alu8_test matches 0 run function alu8_test:fail',
               'scoreboard players add #case alu8_test 1',
               'execute store result storage alu8_test:results checked int 1 run scoreboard players get #case alu8_test']
    checks += [f'execute if score #case alu8_test matches {i} run function alu8_test:apply_{i}'
               for i in range(1,len(vectors))]
    checks.append(f'execute if score #case alu8_test matches {len(vectors)} run function alu8_test:finish')
    write('check',checks)
    write('fail',['execute if score #failed alu8_test matches ..31 run function alu8_test:record_failure',
                  'scoreboard players add #failed alu8_test 1'])
    write('record_failure',['data modify storage alu8_test:results failures append value {}']+
          [f'execute store result storage alu8_test:results failures[-1].{name} int 1 run scoreboard players get #{name} alu8_test'
           for name in ('case','a','b','op','result','zero','actual','actual_zero')])
    write('finish',['data modify storage alu8_test:results status set value "complete"']+
          [f'execute store result storage alu8_test:results {name} int 1 run scoreboard players get #{name} alu8_test'
           for name in ('passed','failed')]+[
          'tellraw @a [{"text":"ALU8 test complete. Passed: "},{"score":{"name":"#passed","objective":"alu8_test"}},{"text":"; failed: "},{"score":{"name":"#failed","objective":"alu8_test"}}]'])
    manifest = {'origin':origin,'pins':pins,'bounds':[low,high],'vectors':vectors,
                'cases':len(vectors),'settle_ticks':settle,'sprint_ticks':len(vectors)*settle+200,
                'placement_batches':len(batches)}
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k != 'vectors'},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('schematic',type=Path)
    parser.add_argument('datapacks',type=Path)
    parser.add_argument('--origin',nargs=3,type=int,required=True)
    parser.add_argument('--settle',type=int,default=400)
    parser.add_argument('--netlist',type=Path,default=Path('output/alu8.json'))
    parser.add_argument('--namespace',default='alu8_test')
    args = parser.parse_args()
    print(f'Netlist/reference checks passed: {verify_netlist(args.netlist,test_vectors())}')
    generate(args.schematic,args.origin,args.datapacks,args.settle,args.namespace)
