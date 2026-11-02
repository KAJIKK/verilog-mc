"""Normalize LUTs and cost compatible cones as shared LUTs or native gates."""
from dataclasses import dataclass
from functools import lru_cache
import math


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


@lru_cache(maxsize=1)
def _primitive_catalog():
    """Truth tables and allocated pitch costs from the actual gate blueprints."""
    from itertools import permutations
    from logic_gates import LogicGates
    catalog = {}
    def add(kind,n,ports,gate,truth,parameters=()):
        data = tuple(int(truth([(address>>i)&1 for i in range(n)])) for address in range(1<<n))
        entry = ((gate.size_x+2)*gate.size_z,kind,tuple(ports),tuple(parameters))
        key = n,data
        if key not in catalog or entry[0] < catalog[key][0]:
            catalog[key] = entry
    add('NOT',1,[('A',0)],LogicGates._not(),lambda v:not v[0])
    for n in range(1,5):
        ports = tuple(zip('ABCD',range(n)))
        add('AND',n,ports,LogicGates.and_gate(n),lambda v:all(v))
        add('NAND',n,ports,LogicGates.nand_gate(n),lambda v:not all(v))
        add('OR',n,ports,LogicGates.or_gate(n),lambda v:any(v))
        add('NOR',n,ports,LogicGates.nor_gate(n),lambda v:not any(v))
    add('XOR',2,[('A',0),('B',1)],LogicGates.xor_gate(),lambda v:v[0] != v[1])
    add('XNOR',2,[('A',0),('B',1)],LogicGates.xnor_gate(),lambda v:v[0] == v[1])
    for a,b,s in permutations(range(3)):
        add('MUX',3,[('A',a),('B',b),('S',s)],LogicGates.mux_gate(),
            lambda v,a=a,b=b,s=s:v[b] if v[s] else v[a])
    for n in range(2,5):
        for pattern in range(1<<n):
            for invert in (0,1):
                add('MC_MINTERM',n,tuple(zip('ABCD',range(n))),
                    LogicGates.minterm_gate(n,pattern,invert),
                    lambda v,p=pattern,inv=invert:all(value == ((p>>i)&1) for i,value in enumerate(v)) ^ inv,
                    (('WIDTH',n),('PATTERN',pattern),('INVERT',invert)))
    return catalog


@dataclass(frozen=True)
class _Piece:
    inputs: tuple
    outputs: tuple
    data: tuple
    kind: str = 'MC_LUT'
    ports: tuple = ()
    parameters: tuple = ()


def _project(n,data,outputs):
    """Extract output columns and remove inputs those columns do not depend on."""
    rows = tuple(sum(((row>>i)&1)<<j for j,i in enumerate(outputs)) for row in data)
    used = tuple(i for i in range(n) if any(rows[a] != rows[a | (1<<i)]
                                         for a in range(1<<n) if not a & (1<<i)))
    reduced = tuple(rows[sum(((a>>j)&1)<<i for j,i in enumerate(used))]
                    for a in range(1<<len(used)))
    return _Piece(used,outputs,reduced)


@lru_cache(maxsize=8192)
def _hybrid_plan(n,m,data,gate_cost_scale):
    """Minimum proxy-cost partition into primitive outputs and shared LUTs.

    At most eight outputs allow subset DP. A native output may be extracted
    without splitting the remaining shared decoder. Compare this same cost
    BEFORE every cone merge, not only after pure-LUT packing has committed.
    """
    pieces,costs = {},{0:0}
    plans = {0:()}
    for mask in range(1,1<<m):
        outputs = tuple(i for i in range(m) if mask & (1<<i))
        piece = _project(n,data,outputs)
        ni,no = len(piece.inputs),len(piece.outputs)
        cost = (2*max(ni,no)+2)*(2*(1<<ni)+2)
        if no == 1:
            native = _primitive_catalog().get((ni,piece.data))
            if native is not None and native[0]*gate_cost_scale < cost:
                cost,kind,ports,parameters = native
                cost *= gate_cost_scale
                piece = _Piece(piece.inputs,piece.outputs,piece.data,kind,
                               tuple((port,piece.inputs[i]) for port,i in ports),parameters)
        pieces[mask] = cost,piece
        # Every partition has exactly one piece containing its lowest set bit.
        # Starting with the whole mask gives deterministic ties favoring sharing.
        best,best_plan = cost,(piece,)
        low,subset = mask & -mask,(mask-1)&mask
        while subset:
            if subset & low:
                value = pieces[subset][0]+costs[mask^subset]
                if value < best:
                    best,best_plan = value,(pieces[subset][1],)+plans[mask^subset]
            subset = (subset-1)&mask
        costs[mask],plans[mask] = best,best_plan
    return costs[(1<<m)-1],plans[(1<<m)-1]


def pack_lut_cells(module,pack=True,*,hybrid=False,gate_cost_scale=1.0):
    """Greedy physical-area reduction, respecting live signals and DAG cuts.

    Merge shared-address LUTs or adjacent cones only if the external interface
    fits and the allocated macro footprint decreases. Never absorb storage.
    """
    if not math.isfinite(gate_cost_scale) or gate_cost_scale <= 0:
        raise ValueError('Gate cost scale must be finite and positive')
    cells = dict(module.get('cells',{}))
    groups = {name:decode_lut(cell) for name,cell in cells.items()
              if cell['type'] in ('$lut','$_LUT_','MC_LUT')}
    if not groups:
        return cells,{}
    original_count = len(groups)
    def cost(lut):
        return (_hybrid_plan(len(lut.inputs),len(lut.outputs),lut.data,gate_cost_scale)[0]
                if hybrid else lut.area)
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
                # The legacy area prefilter is valid only for pure-LUT mapping.
                # Hybrid decisions also account for native gates and support
                # reduction after extracting a subset of output columns.
                if not hybrid and (ga.area+gb.area-area <= 0 or
                                   (best is not None and ga.area+gb.area-area <= best[0])):
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
                merged = Lut(ins,outs,tuple(data))
                gain = cost(ga)+cost(gb)-cost(merged)
                if gain > 0 and (best is None or gain > best[0]):
                    best = gain,a,b,merged
        if best is None:
            break
        _,a,b,merged = best
        groups[a] = merged
        del groups[b]
        del cells[b]
        merges += 1
    if not hybrid:
        cells.update({name:encode_lut(g) for name,g in groups.items()})
        return cells,{'original_luts':original_count,'packed_luts':len(groups),'merges':merges}
    for name in groups:
        del cells[name]
    counts = {}
    for name,g in groups.items():
        _,plan = _hybrid_plan(len(g.inputs),len(g.outputs),g.data,gate_cost_scale)
        for index,piece in enumerate(plan):
            key = name if len(plan) == 1 else f'{name}$hybrid${index}'
            while key in cells:
                key += '_'
            if piece.kind == 'MC_LUT':
                cell = encode_lut(Lut(tuple(g.inputs[i] for i in piece.inputs),
                                      tuple(g.outputs[i] for i in piece.outputs),piece.data))
            else:
                connections = {port:[g.inputs[i]] for port,i in piece.ports}
                connections['Y'] = [g.outputs[piece.outputs[0]]]
                cell = {'type':piece.kind,'parameters':dict(piece.parameters),'connections':connections,
                        'port_directions':{port:'output' if port == 'Y' else 'input' for port in connections}}
            cells[key] = cell
            counts[piece.kind] = counts.get(piece.kind,0)+1
    return cells,{'original_luts':original_count,'packed_luts':counts.get('MC_LUT',0),'merges':merges,
                  'mapping':'hybrid','primitive_cells':sum(v for k,v in counts.items() if k != 'MC_LUT'),
                  'cell_counts':counts,'gate_cost_scale':gate_cost_scale,
                  'estimated_area':sum(cost(g) for g in groups.values())}


def map_hybrid_design(design,gate_cost_scale=1.0):
    """Return mapped Yosys JSON, preserving the input and all signal interfaces."""
    import copy
    import json
    result = copy.deepcopy(design)
    for module in result.get('modules',{}).values():
        if parameter_int(module.get('attributes',{}).get('mc_hybrid_mapped',0)):
            continue
        if not any(c['type'] in ('$lut','$_LUT_','MC_LUT') for c in module.get('cells',{}).values()):
            continue
        cells,stats = pack_lut_cells(module,hybrid=True,gate_cost_scale=gate_cost_scale)
        module['cells'] = cells
        attributes = module.setdefault('attributes',{})
        attributes['mc_hybrid_mapped'] = 1
        attributes['mc_mapping_stats'] = json.dumps(stats,sort_keys=True)
    return result


def estimate_layout(design):
    """Actual gate placement + minimum channels; no routing/search or synthesis.

    This proxy includes row padding, named pin heights, and relay insertion.
    It ranks candidates cheaply; routed footprint remains the final metric.
    """
    import contextlib
    import io
    from intermediate_circuit import IntermediateCircuit
    from netlist_parser import parse_yosys_data
    with contextlib.redirect_stdout(io.StringIO()):
        ic = IntermediateCircuit()
        ic.load_graph(parse_yosys_data(design))
        ic.build_gates()
        ic.place_gates()
    width = max((g.x_offset+g.size_x+2 for row in ic.gate_layers for g in row),default=0)
    length = sum(max((g.size_z for g in row),default=0) for row in ic.gate_layers)+3*max(0,len(ic.gate_layers)-1)
    return {'proxy_dimensions':[width,length],'proxy_footprint':width*length,'layers':len(ic.gate_layers)}


def choose_hybrid_design(candidates,gate_cost_scale=1.0):
    """Choose between ABC cuts by physical-row estimates, retaining all scores."""
    import json
    mapped = [(name,map_hybrid_design(data,gate_cost_scale)) for name,data in candidates]
    scores = [dict(source=name,**estimate_layout(data)) for name,data in mapped]
    index = min(range(len(mapped)),key=lambda i:scores[i]['proxy_footprint'])
    name,result = mapped[index]
    for module in result['modules'].values():
        attributes = module.get('attributes',{})
        if 'mc_mapping_stats' in attributes:
            stats = json.loads(attributes['mc_mapping_stats'])
            stats.update(selected_source=name,candidate_layouts=scores)
            attributes['mc_mapping_stats'] = json.dumps(stats,sort_keys=True)
    return result


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Physically costed hybrid gate/LUT mapping of Yosys JSON')
    parser.add_argument('netlist',type=Path)
    parser.add_argument('--output',type=Path,help='Default: replace the generated input JSON')
    parser.add_argument('--candidate',action='append',type=Path,default=[],help='Compare another ABC netlist before choosing')
    parser.add_argument('--hybrid',action='store_true',required=True)
    parser.add_argument('--gate-cost-scale',type=float,default=1.0)
    args = parser.parse_args()
    sources = [args.netlist]+args.candidate
    result = choose_hybrid_design([(str(p),json.loads(p.read_text())) for p in sources],args.gate_cost_scale)
    (args.output or args.netlist).write_text(json.dumps(result,indent=2)+'\n')
    for name,module in result['modules'].items():
        if 'mc_mapping_stats' in module.get('attributes',{}):
            print(name,module['attributes']['mc_mapping_stats'])
