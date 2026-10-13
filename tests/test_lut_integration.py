"""Truth-table packing, signal identity and LUT compilation regressions."""
import json
from pathlib import Path
import tempfile
import unittest

from generate_lut import build_lut
from lut_mapping import Lut,decode_lut,encode_lut,pack_lut_cells
from netlist_parser import parse_yosys_json,VertexType
from tests.generate_alu_test import reference,test_vectors,verify_netlist


def evaluate(graph,inputs):
    drivers = {bit:v for v in graph.vertices.values() for bit in getattr(v,'bits',[])
               if v.type != VertexType.OUTPUT}
    values = {'0':False,'1':True}
    for v in graph.vertices.values():
        if v.type == VertexType.INPUT:
            values[v.bits[0]] = bool(inputs[v.name])
    def value(bit):
        if bit not in values:
            v = drivers[bit]
            if v.func_type != 'LUT':
                raise ValueError('This evaluator expects combinational LUTs')
            address = sum(int(value(bits[0]))<<i for i,bits in enumerate(v.input_bits.values()))
            row = v.lut_data[address]
            values.update({bits[0]:bool((row>>i)&1) for i,bits in enumerate(v.output_bits.values())})
        return values[bit]
    return {v.name:value(v.bits[0]) for v in graph.vertices.values() if v.type == VertexType.OUTPUT}


class LutIntegrationTests(unittest.TestCase):
    def test_address_order_constants_and_aliases(self):
        cell = {'connections':{'A':[2,3],'Y':[4]},'parameters':{'WIDTH':'10','LUT':'0010'}}
        self.assertEqual(decode_lut(cell).data,(0,1,0,0))
        cell['connections']['A'] = [2,'0']
        self.assertEqual(decode_lut(cell).data,(0,1))
        cell['connections']['A'] = [2,2]
        self.assertEqual(decode_lut(cell).data,(0,0))

    def test_packing_shared_address_retains_distinct_outputs(self):
        xor = Lut((2,3),(4,),(0,1,1,0))
        and_gate = Lut((3,2),(5,),(0,0,0,1))
        module = {'ports':{'out':{'direction':'output','bits':[4,5]}},
                  'cells':{'xor':encode_lut(xor),'and':encode_lut(and_gate)}}
        cells,stats = pack_lut_cells(module)
        self.assertEqual(stats['packed_luts'],1)
        packed = decode_lut(next(iter(cells.values())))
        self.assertEqual(packed.outputs,(4,5))
        self.assertEqual(packed.data,(0,1,1,2))

    def test_adjacent_cone_eliminates_internal_only_signal(self):
        cells = {'a':encode_lut(Lut((2,),(3,),(1,0))),
                 'b':encode_lut(Lut((3,),(4,),(1,0)))}
        packed,_ = pack_lut_cells({'cells':cells,'ports':{'y':{'direction':'output','bits':[4]}}})
        lut = decode_lut(next(iter(packed.values())))
        self.assertEqual(lut.outputs,(4,))
        self.assertEqual(lut.data,(0,1))

    def test_nonconvex_contraction_does_not_create_a_cycle(self):
        cells = {'a':encode_lut(Lut((2,),(3,),(0,1))),
                 'middle':{'type':'NOT','connections':{'A':[3],'Y':[4]}},
                 'b':encode_lut(Lut((3,4),(5,),(0,1,1,0)))}
        _,stats = pack_lut_cells({'cells':cells,'ports':{'y':{'direction':'output','bits':[5]}}})
        self.assertEqual(stats['packed_luts'],2)

    def test_invalid_limits_and_unknown_truth_bits_fail(self):
        for n,m,data in ((5,1,[0]*32),(1,9,[0,0]),(-1,1,[]),(1,0,[0,0]),(1,1,[0,2])):
            with self.assertRaises(ValueError):
                build_lut(n,m,data)
        with self.assertRaises(ValueError):
            decode_lut({'connections':{'A':[2],'Y':[3]},'parameters':{'WIDTH':1,'LUT':'x0'}})

    def test_buffered_interfaces_cover_all_supported_shapes(self):
        for n in range(5):
            for m in range(1,9):
                gate = build_lut(n,m,[0]*(1<<n))
                self.assertEqual(gate.pin_positions(False),[(2*j+1,5) for j in range(n)])
                self.assertEqual(gate.pin_positions(True),[(2*j,1) for j in range(m)])
                for x,y in gate.pin_positions(False):
                    self.assertIn('repeater',gate.blocks[(x,y,0)])
                for x,y in gate.pin_positions(True):
                    self.assertIn('repeater',gate.blocks[(x,y,gate.size_z-1)])

    def test_boolean_truth_entries_are_supported(self):
        self.assertEqual(build_lut(1,1,[False,True]).lut_data,(0,1))

    def test_duplicate_output_signal_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            decode_lut(encode_lut(Lut((2,),(3,3),(0,3))))

    def test_storage_cells_remain_storage_in_a_mixed_lut_design(self):
        module = {'ports':{'d':{'direction':'input','bits':[2]},
                           'e':{'direction':'input','bits':[3]},
                           'q':{'direction':'output','bits':[5]}},
                  'cells':{'logic':encode_lut(Lut((2,),(4,),(1,0))),
                           'storage':{'type':'$_DLATCH_P_',
                                      'connections':{'D':[4],'E':[3],'Q':[5]}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'mixed.json'
            path.write_text(json.dumps({'modules':{'mixed':module}}))
            graph = parse_yosys_json(path)
        storage = graph.vertices['storage']
        self.assertEqual(storage.func_type,'$_DLATCH_P_')
        self.assertEqual(storage.input_bits,{'D':[4],'E':[3]})
        self.assertEqual(storage.output_bits,{'Q':[5]})
        self.assertEqual(graph.lut_stats['packed_luts'],1)

    def test_literal_output_is_explicitly_driven(self):
        data = {'modules':{'constant':{'ports':{'y':{'direction':'output','bits':['1']}},'cells':{}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'constant.json'
            path.write_text(json.dumps(data))
            graph = parse_yosys_json(path)
        source = graph.vertices['y'].before[0]
        self.assertEqual(source.lut_data,(1,))
        self.assertFalse(source.input_bits)

    def test_packed_adder_matches_every_input_combination(self):
        path = Path('output/adder4_lut.json')
        if not path.exists():
            self.skipTest('Run make TOP=adder4 MAPPING=lut')
        graph = parse_yosys_json(path)
        for a in range(16):
            for b in range(16):
                inputs = {f'{port}[{i}]':(val>>i)&1 for port,val in (('a',a),('b',b)) for i in range(4)}
                out = evaluate(graph,inputs)
                self.assertEqual(sum(int(out[f'sum[{i}]'])<<i for i in range(5)),a+b)

    def test_packed_alu_matches_reference_and_unpacked_netlist(self):
        path = Path('output/alu8_lut.json')
        if not path.exists():
            self.skipTest('Run make TOP=alu8 MAPPING=lut')
        vectors = test_vectors()
        self.assertEqual(verify_netlist(path,vectors),len(vectors))
        graph = parse_yosys_json(path)
        for vector in vectors:
            inputs = {f'{port}[{i}]':(vector[port]>>i)&1 for port,width in (('a',8),('b',8),('op',2)) for i in range(width)}
            out = evaluate(graph,inputs)
            self.assertEqual((sum(int(out[f'result[{i}]'])<<i for i in range(9)),int(out['zero'])),
                             reference(vector['a'],vector['b'],vector['op']))


if __name__ == '__main__':
    unittest.main()
