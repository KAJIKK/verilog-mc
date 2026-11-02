"""Compare postprocessors on identical raw geometry; reuse cached routing."""
import argparse
import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import statistics
from time import perf_counter

from generate_schem import resolve_redstone_wires
from intermediate_circuit import IntermediateCircuit
from netlist_parser import parse_yosys_json
from repeater_postprocessor import build_graph,build_graph_baseline
from tests.repeater_stress import Fixture,stress_fixtures


def design_fixture(path):
    ic = IntermediateCircuit()
    ic.load_graph(parse_yosys_json(str(path)))
    ic.build_gates()
    ic.route_channels()
    circuit,sources,fixed = ic.gen_circuit()
    return Fixture(path.stem,resolve_redstone_wires(circuit.blocks),sources,[])


def router_fixtures():
    from router import route
    from tests.generate_router_test import CASES
    fixtures = []
    for name,nets,options in CASES:
        circuit = route(nets,**options)
        fixtures.append(Fixture('router_'+name,resolve_redstone_wires(circuit.blocks),
                                [(pins[0],15,'south') for pins in circuit.net_pins if pins],
                                [sorted(wires) for wires in circuit.net_wires]))
    return fixtures


def save_corpus(path,fixtures):
    path.parent.mkdir(parents=True,exist_ok=True)
    records = [dict(name=f.name,blocks=list(f.blocks.items()),sources=f.sources,
                    nets=f.nets,expected_error=f.expected_error) for f in fixtures]
    with gzip.open(path,'wt') as stream:
        json.dump(records,stream)


def load_corpus(path):
    with gzip.open(path,'rt') as stream:
        records = json.load(stream)
    return [Fixture(r['name'],{tuple(p):s for p,s in r['blocks']},
                    [(tuple(p),power,d) for p,power,d in r['sources']],
                    [[tuple(p) for p in net] for net in r['nets']],r['expected_error']) for r in records]


def measure(fixture,algorithm):
    started = perf_counter()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _,repeaters = algorithm(fixture.blocks,fixture.sources)
        return dict(repeaters=len(repeaters),seconds=perf_counter()-started,
                    placements=[[p,d] for p,d in sorted(repeaters.items())])
    except ValueError as error:
        return dict(error=str(error),seconds=perf_counter()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design',type=Path,action='append',default=[])
    parser.add_argument('--corpus',type=Path,default=Path('output/repeater_corpus.json.gz'))
    parser.add_argument('--rebuild',action='store_true')
    parser.add_argument('--router',action='store_true',help='Include existing 3D routing fixtures')
    parser.add_argument('--results',type=Path,default=Path('tests/repeater_results.json'))
    parser.add_argument('--repeat',type=int,default=3)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('repeat must be positive')
    if args.corpus.exists() and not args.rebuild:
        fixtures = load_corpus(args.corpus)
    else:
        fixtures = stress_fixtures()+(router_fixtures() if args.router else [])+[design_fixture(p) for p in args.design]
        save_corpus(args.corpus,fixtures)
    results = []
    for fixture in fixtures:
        result = dict(name=fixture.name,signal_blocks=sum('wire' in s or 'repeater' in s for s in fixture.blocks.values()),
                      fixed_repeaters=sum('minecraft:repeater' in s for s in fixture.blocks.values()),
                      expected_error=fixture.expected_error,
                      geometry_sha256=hashlib.sha256(json.dumps(
                          [list(fixture.blocks.items()),fixture.sources],separators=(',',':')).encode()).hexdigest())
        for name,algorithm in (('baseline',build_graph_baseline),('optimized',build_graph)):
            runs = [measure(fixture,algorithm) for _ in range(args.repeat)]
            result[name] = runs[-1]
            result[name]['samples_seconds'] = [run['seconds'] for run in runs]
            result[name]['seconds'] = statistics.median(result[name]['samples_seconds'])
        results.append(result)
        print(f'{fixture.name}: baseline={result["baseline"].get("repeaters", "error")} '
              f'optimized={result["optimized"].get("repeaters", "error")}',flush=True)
        args.results.write_text(json.dumps(results,indent=2)+'\n')


if __name__ == '__main__':
    main()
