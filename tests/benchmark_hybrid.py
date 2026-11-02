"""Rank hybrid mappings cheaply, route a shortlist, and optionally prove RTL equivalence."""
import argparse
import contextlib
from collections import Counter
import io
import hashlib
import json
from pathlib import Path
import subprocess
from time import perf_counter

from intermediate_circuit import IntermediateCircuit
from lut_mapping import decode_lut,map_hybrid_design
from netlist_parser import parse_yosys_json
from repeater_postprocessor import build_graph
from generate_schem import resolve_redstone_wires


def verilog_model(module,name='gate'):
    """Independent combinational RTL for Yosys SAT equivalence, including LUTs."""
    def identifier(value):
        return '\\'+value+' '
    def bit(value):
        return f'n{value}' if type(value) is int else f"1'b{value}"
    ports = module['ports']
    lines = [f'module {name}('+','.join(identifier(p) for p in ports)+');']
    signals = {b for p in ports.values() for b in p['bits'] if type(b) is int}
    signals.update(b for c in module['cells'].values() for bs in c['connections'].values() for b in bs if type(b) is int)
    lines += ['wire '+','.join(bit(b) for b in sorted(signals))+';']
    for port,data in ports.items():
        width = len(data['bits'])
        shape = f'[{width-1}:0] ' if width > 1 else ''
        lines.append(f'{data["direction"]} {shape}{identifier(port)};')
        for index,b in enumerate(data['bits']):
            pin = identifier(port)+(f'[{index}]' if width > 1 else '')
            lines.append(f'assign '+(f'{bit(b)} = {pin};' if data['direction'] == 'input' else f'{pin} = {bit(b)};'))
    for index,cell in enumerate(module['cells'].values()):
        if cell['type'] in ('$lut','$_LUT_','MC_LUT'):
            lut = decode_lut(cell)
            count = len(lut.outputs)
            target = '{'+','.join(bit(b) for b in reversed(lut.outputs))+'}'
            table = sum(row<<(i*count) for i,row in enumerate(lut.data))
            if not lut.inputs:
                lines.append(f'assign {target} = {count}\'d{table};')
                continue
            width = len(lut.data)*count
            lines.append(f'localparam [{width-1}:0] T{index} = {width}\'h{table:x};')
            address = '{'+','.join(bit(b) for b in reversed(lut.inputs))+'}'
            lines.append(f'assign {target} = T{index}[{address} * {count} +: {count}];')
        else:
            args = {p:bit(bs[0]) for p,bs in cell['connections'].items() if p != 'Y'}
            kind = cell['type']
            if kind == 'MC_MINTERM':
                width = len(args)
                pattern = cell['parameters']['PATTERN']
                expression = '('+'{'+','.join(args[p] for p in reversed('ABCD'[:width]))+'}'+f' == {width}\'d{pattern})'
                if cell['parameters'].get('INVERT',0):
                    expression = '~'+expression
            elif kind == 'NOT':
                expression = '~'+args['A']
            elif kind == 'MUX':
                expression = f'({args["S"]} ? {args["B"]} : {args["A"]})'
            elif kind in ('AND','NAND','OR','NOR','XOR','XNOR'):
                operator = '&' if kind in ('AND','NAND') else '|' if kind in ('OR','NOR') else '^'
                expression = '('+operator.join(args.values())+')'
                if kind in ('NAND','NOR','XNOR'):
                    expression = '~'+expression
            else:
                raise ValueError(f'No combinational equivalence model for {kind}')
            lines.append(f'assign {bit(cell["connections"]["Y"][0])} = {expression};')
    return '\n'.join(lines+['endmodule',''])


def prove(path,source,top):
    design = json.loads(path.read_text())
    model = path.with_suffix('.equiv.v')
    model.write_text(verilog_model(design['modules'][top]))
    script = (f'read_verilog "{source}"; prep -top {top}; rename {top} gold; '
              f'read_verilog "{model}"; proc; opt; equiv_make gold gate equiv; '
              'hierarchy -top equiv; equiv_simple; equiv_status -assert')
    started = perf_counter()
    result = subprocess.run(['yosys','-Q','-T','-p',script],capture_output=True,text=True,timeout=60)
    path.with_suffix('.equiv.log').write_text(result.stdout+result.stderr)
    if result.returncode:
        raise RuntimeError(f'Equivalence failed; see {path.with_suffix(".equiv.log")}')
    return {'passed':True,'seconds':perf_counter()-started,'method':'Yosys equiv_simple SAT against original RTL'}


def prepare(path,place=True):
    ic = IntermediateCircuit()
    with contextlib.redirect_stdout(io.StringIO()):
        graph = parse_yosys_json(path)
        ic.load_graph(graph)
        ic.build_gates()
        if place:
            ic.place_gates()
    return ic


def proxy(path):
    ic = prepare(path)
    width = max(g.x_offset+g.size_x+2 for row in ic.gate_layers for g in row)
    length = sum(max(g.size_z for g in row) for row in ic.gate_layers)+3*(len(ic.gate_layers)-1)
    counts = Counter(getattr(v,'func_type',v.type) for row in ic.vertex_layers for v in row)
    return dict(proxy_footprint=width*length,proxy_dimensions=[width,length],
                layers=len(ic.gate_layers),cell_counts=dict(counts),mapping=ic.lut_stats)


def physical(path):
    ic = prepare(path,place=False)
    started = perf_counter()
    ic.route_channels()
    circuit,sources,fixed = ic.gen_circuit()
    route_seconds = perf_counter()-started
    started = perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        _,repeaters = build_graph(resolve_redstone_wires(circuit.blocks),sources)
    return dict(dimensions=[circuit.size_x,circuit.size_y,circuit.size_z],
                footprint=circuit.size_x*circuit.size_z,added_repeaters=len(repeaters),
                fixed_repeaters=len(fixed),total_repeaters=len(fixed)+len(repeaters),
                routing_seconds=route_seconds,postprocessing_seconds=perf_counter()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design',type=Path,default=Path('output/alu8_lut.json'))
    parser.add_argument('--scales',nargs='+',type=float,default=[0.5,1,2,4])
    parser.add_argument('--route-best',type=int,default=2)
    parser.add_argument('--formal-source',type=Path)
    parser.add_argument('--results',type=Path,default=Path('output/hybrid_sweep.json'))
    args = parser.parse_args()
    if args.route_best < 0:
        parser.error('route-best must be nonnegative')
    data = json.loads(args.design.read_text())
    top = next(name for name,m in data['modules'].items() if m.get('cells'))
    results = [dict(name='lut_baseline',path=str(args.design),**proxy(args.design))]
    for scale in args.scales:
        path = args.design.with_name(args.design.stem.removesuffix('_lut')+f'_hybrid_s{scale:g}.json')
        path.write_text(json.dumps(map_hybrid_design(data,scale),indent=2)+'\n')
        row = dict(name=f'hybrid_s{scale:g}',path=str(path),**proxy(path))
        mapped = json.loads(path.read_text())
        row['cells_sha256'] = hashlib.sha256(json.dumps(mapped['modules'][top]['cells'],sort_keys=True).encode()).hexdigest()
        if args.formal_source:
            row['equivalence'] = prove(path,args.formal_source,top)
        results.append(row)
        print(json.dumps(row),flush=True)
    shortlist,seen = set(),set()
    for row in sorted(results[1:],key=lambda r:r['proxy_footprint']):
        if row['cells_sha256'] not in seen and len(shortlist) < args.route_best:
            seen.add(row['cells_sha256'])
            shortlist.add(row['name'])
    for row in results:
        if row['name'] == 'lut_baseline' or row['name'] in shortlist:
            try:
                row['physical'] = physical(Path(row['path']))
            except ValueError as error:
                row['physical'] = {'error':str(error)}
            print(row['name'],json.dumps(row['physical']),flush=True)
            args.results.write_text(json.dumps(results,indent=2)+'\n')
    args.results.write_text(json.dumps(results,indent=2)+'\n')


if __name__ == '__main__':
    main()
