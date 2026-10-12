"""Repeatable routing-only benchmarks; no schematics or world writes."""
import argparse
import contextlib
import json
import statistics
import sys
from time import perf_counter

from tests.generate_router_test import CASES
from intermediate_circuit import IntermediateCircuit
from netlist_parser import parse_yosys_json
from router import route


def benchmark(repeat=3, cases=None, design=None, workers=None):
    results = []
    for name,nets,options in CASES:
        if cases is not None and name not in cases:
            continue
        times = []
        for _ in range(repeat):
            started = perf_counter()
            circuit = route(nets,**options)
            times.append(perf_counter()-started)
        results.append({'case':name,'median_seconds':statistics.median(times),
                        'samples_seconds':times,
                        'dimensions':[circuit.size_x,circuit.size_y,circuit.size_z],
                        'attempts':circuit.route_stats['attempts']})
    if design is not None:
        times = []
        for _ in range(repeat):
            ic = IntermediateCircuit()
            with contextlib.redirect_stdout(sys.stderr):
                ic.load_graph(parse_yosys_json(design))
                ic.build_gates()
                started = perf_counter()
                ic.route_channels(workers=workers)
                times.append(perf_counter()-started)
        results.append({'design':str(design),'workers':workers or 'automatic',
                        'median_seconds':statistics.median(times),'samples_seconds':times,
                        'channels':[{'dimensions':[c.circuit.size_x,c.circuit.size_y,c.circuit.size_z],
                                     'seconds':c.circuit.route_stats['seconds']} for c in ic.channels]})
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',action='append',choices=[name for name,_,_ in CASES])
    parser.add_argument('--design',help='Yosys JSON design; timing excludes parsing and gate construction')
    parser.add_argument('--workers',type=int,help='Channel workers; 1 measures serial routing')
    parser.add_argument('--repeat',type=int,default=3)
    args = parser.parse_args()
    if args.repeat < 1 or (args.workers is not None and args.workers < 1):
        parser.error('repeat and workers must be positive')
    selected = args.case if args.case is not None else [] if args.design else None
    print(json.dumps(benchmark(args.repeat,selected,args.design,args.workers),indent=2))
