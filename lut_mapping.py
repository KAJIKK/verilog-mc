"""Normalize Yosys LUTs and pack compatible cones into multi-output LUTs."""
from dataclasses import dataclass


def parameter_int(value):
    if isinstance(value,str):
        if not value or any(c not in '01' for c in value):
            raise ValueError(f'Unknown/non-binary LUT parameter: {value!r}')
        return int(value,2)
    if type(value) is not int or value < 0:
        raise ValueError(f'Invalid LUT parameter: {value!r}')
    return value


@dataclass(frozen=True)
class Lut:
    inputs: tuple
    outputs: tuple
    data: tuple

    @property
    def area(self):
        # Allocated even-origin pitch includes the gate-row separator.
        return (2*max(len(self.inputs),len(self.outputs))+2)*(2*(1<<len(self.inputs))+2)


def decode_lut(cell):
    inputs = tuple(cell['connections']['A'])
    outputs = tuple(cell['connections']['Y'])
    width = parameter_int(cell['parameters']['WIDTH'])
    count = parameter_int(cell['parameters'].get('OUTPUTS',1))
    table = parameter_int(cell['parameters']['LUT'])
    if width != len(inputs) or not 0 <= width <= 4 or count != len(outputs) or not 1 <= count <= 8:
        raise ValueError('LUT interface exceeds 4 inputs/8 outputs or disagrees with parameters')
    if len(set(outputs)) != count or any(type(bit) is not int for bit in outputs):
        raise ValueError('LUT outputs must be distinct signal-bit identifiers')
    if table >= 1 << ((1<<width)*count):
        raise ValueError('LUT table contains more bits than its declared interface')
    # Fold constants and aliases, preserving the original A[0] address weight.
    pins = tuple(dict.fromkeys(bit for bit in inputs if type(bit) is int))
    if any(type(bit) is not int and bit not in ('0','1') for bit in inputs):
        raise ValueError('LUT addresses cannot contain unknown/high-impedance bits')
    data = []
    for address in range(1<<len(pins)):
        values = {bit:(address>>i)&1 for i,bit in enumerate(pins)}
        values.update({'0':0,'1':1})
        original = sum(values[bit]<<i for i,bit in enumerate(inputs))
        data.append((table>>(original*count)) & ((1<<count)-1))
    return Lut(pins,outputs,tuple(data))


def encode_lut(lut):
    count = len(lut.outputs)
    table = sum(value<<(i*count) for i,value in enumerate(lut.data))
    return {'type':'MC_LUT','parameters':{'WIDTH':len(lut.inputs),'OUTPUTS':count,'LUT':table},
            'port_directions':{'A':'input','Y':'output'},
            'connections':{'A':list(lut.inputs),'Y':list(lut.outputs)}}


def pack_lut_cells(module,pack=True):
    """Greedy physical-area reduction, respecting live signals and DAG cuts.

    Merge shared-address LUTs or adjacent cones only if the external interface
    fits and the allocated macro footprint decreases. Never absorb storage.
    """
    cells = dict(module.get('cells',{}))
    groups = {name:decode_lut(cell) for name,cell in cells.items()
              if cell['type'] in ('$lut','$_LUT_','MC_LUT')}
    if not groups:
        return cells,{}
    original_count = len(groups)
    merges = 0
    def interfaces(name):
        if name in groups:
            g = groups[name]
            return g.inputs,g.outputs
        c = cells[name]
        directions = c.get('port_directions',{})
        ins,outs = [],[]
        for port,bits in c['connections'].items():
            (outs if directions.get(port,'output' if port in ('Y','Q','QN') else 'input') == 'output' else ins).extend(bits)
        return ins,outs
    while pack:
        names = list(groups)
        links = {name:interfaces(name) for name in cells}
        drivers = {bit:name for name,(_,outs) in links.items() for bit in outs}
        successors = {name:set() for name in cells}
        users = {}
        for name,(ins,_) in links.items():
            for bit in ins:
                users.setdefault(bit,set()).add(name)
                if bit in drivers:
                    successors[drivers[bit]].add(name)
        external = {bit for port in module.get('ports',{}).values()
                    if port['direction'] == 'output' for bit in port['bits']}
        def crosses_outside(a,b):
            # A direct dependency is allowed. A path through an unabsorbed
            # third cell would create a cycle after contraction.
            todo = list(successors[a]-{a,b})
            seen = {a}
            while todo:
                v = todo.pop()
                if v == b:
                    return True
                if v not in seen:
                    seen.add(v)
                    todo.extend(successors[v]-seen)
            return False
        best = None
        for i,a in enumerate(names):
            for b in names[i+1:]:
                ga,gb = groups[a],groups[b]
                if set(ga.inputs).intersection(gb.outputs) and set(gb.inputs).intersection(ga.outputs):
                    continue
                all_out = set(ga.outputs+gb.outputs)
                ins = tuple(dict.fromkeys(bit for bit in ga.inputs+gb.inputs if bit not in all_out))
                outs = tuple(bit for bit in ga.outputs+gb.outputs
                             if bit in external or users.get(bit,set())-{a,b})
                if len(ins) > 4 or not 1 <= len(outs) <= 8:
                    continue
                area = (2*max(len(ins),len(outs))+2)*(2*(1<<len(ins))+2)
                gain = ga.area+gb.area-area
                if gain <= 0 or (best is not None and gain <= best[0]):
                    continue
                if crosses_outside(a,b) or crosses_outside(b,a):
                    continue
                order = (gb,ga) if set(ga.inputs).intersection(gb.outputs) else (ga,gb)
                data = []
                for address in range(1<<len(ins)):
                    values = {bit:(address>>j)&1 for j,bit in enumerate(ins)}
                    for g in order:
                        value = g.data[sum(values[bit]<<j for j,bit in enumerate(g.inputs))]
                        values.update({bit:(value>>j)&1 for j,bit in enumerate(g.outputs)})
                    data.append(sum(values[bit]<<j for j,bit in enumerate(outs)))
                best = gain,a,b,Lut(ins,outs,tuple(data))
        if best is None:
            break
        _,a,b,merged = best
        groups[a] = merged
        del groups[b]
        del cells[b]
        merges += 1
    cells.update({name:encode_lut(g) for name,g in groups.items()})
    return cells,{'original_luts':original_count,'packed_luts':len(groups),'merges':merges}
