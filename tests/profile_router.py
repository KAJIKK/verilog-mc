"""Profile one real channel, independently of Minecraft and process startup."""
import argparse
import cProfile
import contextlib
import hashlib
import io
import json
from pathlib import Path
import pstats
from time import perf_counter

from intermediate_circuit import IntermediateCircuit
from netlist_parser import parse_yosys_json
from router import route


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design',required=True)
    parser.add_argument('--channel',type=int,required=True,help='One-based channel index')
    parser.add_argument('--profile',help='Optional cProfile output path')
    parser.add_argument('--output',help='Optional JSON measurement path')
    args = parser.parse_args()
    ic = IntermediateCircuit()
    with contextlib.redirect_stdout(io.StringIO()):
        ic.load_graph(parse_yosys_json(args.design))
        ic.build_gates()
        jobs = ic.prepare_routing_jobs()
    if not 1 <= args.channel <= len(jobs):
        parser.error('channel is outside the design')
    nets,_,_,width,_,headroom = jobs[args.channel-1]
    profiler = cProfile.Profile() if args.profile else None
    started = perf_counter()
    if profiler:
        profiler.enable()
    circuit = route(nets,min_width=width,pin_headroom=headroom)
    if profiler:
        profiler.disable()
        profiler.dump_stats(args.profile)
        pstats.Stats(profiler).strip_dirs().sort_stats('cumtime').print_stats(25)
    elapsed = perf_counter()-started
    digest = hashlib.sha256(repr(sorted(circuit.blocks.items())).encode()).hexdigest()
    result = {'design':args.design,'channel':args.channel,'nets':len(nets),
              'seconds':elapsed,'profiled':bool(profiler),
              'dimensions':[circuit.size_x,circuit.size_y,circuit.size_z],
              'geometry_sha256':digest,'stats':circuit.route_stats}
    print(json.dumps(result,indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(result,indent=2)+'\n')


if __name__ == '__main__':
    main()
