"""Independent truth evaluation, decoder sharing, and physical pin regressions."""
import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from intermediate_circuit import IntermediateCircuit
from lut_mapping import Lut,decode_lut,encode_lut,map_hybrid_design,pack_lut_cells
from netlist_parser import Vertex,VertexType,parse_yosys_json


def evaluate(module,inputs):
    values = dict(inputs)
    values.update({'0':0,'1':1})
    drivers = {b:c for c in module['cells'].values() for port,bits in c['connections'].items()
               if c.get('port_directions',{}).get(port,'output' if port == 'Y' else 'input') == 'output'
               for b in bits}
    active = set()
    def value(bit):
        if bit not in values:
            if bit in active:
                raise AssertionError('Mapping introduced a combinational cycle')
            active.add(bit)
            c = drivers[bit]
            if c['type'] in ('$lut','$_LUT_','MC_LUT'):
                lut = decode_lut(c)
                row = lut.data[sum(value(b)<<i for i,b in enumerate(lut.inputs))]
                values.update({b:(row>>i)&1 for i,b in enumerate(lut.outputs)})
            else:
                args = {port:value(bits[0]) for port,bits in c['connections'].items() if port != 'Y'}
                kind = c['type']
                if kind == 'MC_MINTERM':
                    pattern = c['parameters']['PATTERN']
                    result = all(args[p] == ((pattern>>i)&1) for i,p in enumerate('ABCD'[:len(args)])) ^ c['parameters']['INVERT']
                elif kind == 'MUX':
                    result = args['B'] if args['S'] else args['A']
                elif kind == 'NOT':
                    result = not args['A']
                elif kind in ('AND','NAND'):
                    result = all(args.values()) ^ (kind == 'NAND')
                elif kind in ('OR','NOR'):
                    result = any(args.values()) ^ (kind == 'NOR')
                elif kind in ('XOR','XNOR'):
                    result = (args['A'] != args['B']) ^ (kind == 'XNOR')
                else:
                    raise AssertionError(kind)
                values[c['connections']['Y'][0]] = int(result)
            active.remove(bit)
        return values[bit]
    return {name:tuple(value(b) for b in port['bits']) for name,port in module['ports'].items()
            if port['direction'] == 'output'}


class HybridMappingTests(unittest.TestCase):
    def check_mapping(self,module,scale=1):
        original = copy.deepcopy(module)
        cells,stats = pack_lut_cells(module,hybrid=True,gate_cost_scale=scale)
        mapped = dict(module,cells=cells)
        inputs = sorted({b for p in module['ports'].values() if p['direction'] == 'input' for b in p['bits']})
        for values in itertools.product((0,1),repeat=len(inputs)):
            assignment = dict(zip(inputs,values))
            self.assertEqual(evaluate(mapped,assignment),evaluate(module,assignment))
        self.assertEqual(module,original)
        return mapped,stats

    def test_every_two_input_truth_table_and_native_four_input_gates(self):
        tables_by_width = [(2,range(16))]
        for n in (3,4):
            mask = (1<<(1<<n))-1
            tables_by_width.append((n,[table for i in range(1<<n) for table in (1<<i,mask^(1<<i))]))
        for n,tables in tables_by_width:
            for table in tables:
                module = {'ports':{'a':{'direction':'input','bits':list(range(2,n+2))},
                                   'y':{'direction':'output','bits':[20]}},
                          'cells':{'logic':encode_lut(Lut(tuple(range(2,n+2)),(20,),
                                                           tuple((table>>i)&1 for i in range(1<<n))))}}
                with self.subTest(n=n,table=table):
                    self.check_mapping(module)

    def test_mux_role_permutations_follow_truth_not_input_order(self):
        for a,b,s in itertools.permutations(range(3)):
            rows = tuple(((i>>b)&1) if (i>>s)&1 else ((i>>a)&1) for i in range(8))
            module = {'ports':{'x':{'direction':'input','bits':[2,3,4]},
                               'y':{'direction':'output','bits':[5]}},
                      'cells':{'mux':encode_lut(Lut((2,3,4),(5,),rows))}}
            mapped,_ = self.check_mapping(module)
            cell = next(iter(mapped['cells'].values()))
            self.assertEqual(cell['type'],'MUX')
            self.assertEqual(cell['connections'],{'A':[2+a],'B':[2+b],'S':[2+s],'Y':[5]})

    def test_shared_decoder_can_beat_individual_native_replacements(self):
        module = {'ports':{'x':{'direction':'input','bits':[2,3]},
                           'y':{'direction':'output','bits':[4,5]}},
                  'cells':{'xor':encode_lut(Lut((2,3),(4,),(0,1,1,0))),
                           'and':encode_lut(Lut((2,3),(5,),(0,0,0,1)))}}
        mapped,stats = self.check_mapping(module,1.5)
        self.assertEqual(len(mapped['cells']),1)
        self.assertEqual(stats['primitive_cells'],0)
        self.assertEqual(set(decode_lut(next(iter(mapped['cells'].values()))).outputs),{4,5})

    def test_extract_cheap_outputs_but_keep_other_outputs_in_shared_lut(self):
        rows = tuple(int(i == 0) | (int(i == 3)<<1) | (int(i in (1,2))<<2) |
                     (int(i in (0,3))<<3) for i in range(4))
        module = {'ports':{'x':{'direction':'input','bits':[2,3]},
                           'y':{'direction':'output','bits':[4,5,6,7]}},
                  'cells':{'shared':encode_lut(Lut((2,3),(4,5,6,7),rows))}}
        mapped,stats = self.check_mapping(module)
        self.assertEqual(stats['cell_counts'],{'NOR':1,'AND':1,'MC_LUT':1})
        self.assertLess(stats['estimated_area'],100)
        self.assertEqual({b for c in mapped['cells'].values() for b in c['connections']['Y']},{4,5,6,7})

    def test_unused_inputs_are_removed_before_matching_native_gate(self):
        module = {'ports':{'x':{'direction':'input','bits':[2,3,4,5]},
                           'y':{'direction':'output','bits':[6]}},
                  'cells':{'wide':encode_lut(Lut((2,3,4,5),(6,),tuple(int((i&5)==5) for i in range(16))))}}
        mapped,_ = self.check_mapping(module)
        c = next(iter(mapped['cells'].values()))
        self.assertEqual(c['type'],'AND')
        self.assertEqual(c['connections'],{'A':[2],'B':[4],'Y':[6]})

    def test_storage_and_external_signal_ids_survive(self):
        storage = {'type':'$_DLATCH_P_','connections':{'D':[4],'E':[3],'Q':[5]}}
        module = {'ports':{'q':{'direction':'output','bits':[5]}},
                  'cells':{'logic':encode_lut(Lut((2,),(4,),(1,0))),'state':storage}}
        cells,_ = pack_lut_cells(module,hybrid=True)
        self.assertEqual(cells['state'],storage)
        self.assertEqual(cells['logic']['connections'],{'A':[2],'Y':[4]})

    def test_frozen_hybrid_mapping_is_not_repacked_by_parser(self):
        module = {'ports':{'x':{'direction':'input','bits':[2,3]},
                           'y':{'direction':'output','bits':[4,5]}},
                  'cells':{'xor':encode_lut(Lut((2,3),(4,),(0,1,1,0))),
                           'and':encode_lut(Lut((2,3),(5,),(0,0,0,1)))}}
        design = map_hybrid_design({'modules':{'test':module}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'hybrid.json'
            path.write_text(json.dumps(design))
            graph = parse_yosys_json(path)
        self.assertEqual(graph.lut_stats['primitive_cells'],2)
        self.assertEqual({v.func_type for v in graph.vertices.values() if v.type == VertexType.FUNCTION},{'XOR','AND'})
        self.assertEqual(map_hybrid_design(design),design,'Frozen output must be safe to read/map again')

    def test_gate_arity_counts_signals_from_one_multioutput_driver(self):
        driver = Vertex('lut',VertexType.FUNCTION,bits=[2,3,4])
        sink = Vertex('and',VertexType.FUNCTION,func_type='AND',before=[driver],
                      input_bits={'A':[2],'B':[3],'C':[4]})
        gate = IntermediateCircuit().gen_gate(sink)
        self.assertEqual(gate.num_inputs,3)
        self.assertEqual(gate.pin_positions(False),[(0,0),(2,0),(4,0)])

    def test_invalid_cost_scales_are_rejected(self):
        for scale in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                pack_lut_cells({},hybrid=True,gate_cost_scale=scale)

    def test_negative_literal_inputs_cannot_backfeed_each_other(self):
        from logic_gates import LogicGates
        from redstone_geometry import signal_powers
        gate = LogicGates.minterm_gate(2,0)
        signals = {p:None for p,s in gate.blocks.items() if 'redstone_wire' in s}
        signals.update({p:(0,1) for p,s in gate.blocks.items() if 'repeater' in s})
        inputs = [(0,1,-1),(2,1,-1)]
        signals.update({p:None for p in inputs})
        solids = set(gate.blocks)-set(signals)
        for a,b in (inputs,list(reversed(inputs))):
            self.assertEqual(signal_powers(signals,solids,a).get(b,0),0)


if __name__ == '__main__':
    unittest.main()
