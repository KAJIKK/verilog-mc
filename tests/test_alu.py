"""Arithmetic reference, mapped netlist and large placement regressions."""
from pathlib import Path
import unittest

from intermediate_circuit import IntermediateCircuit
from netlist_parser import Vertex, VertexType
from tests.generate_adder_test import fill_commands
from tests.generate_alu_test import reference,test_vectors,verify_netlist


class AluTests(unittest.TestCase):
    def test_reference_carry_borrow_and_zero_semantics(self):
        cases = [(255,1,0,(256,1)),(255,255,0,(510,0)),
                 (0,1,1,(255,0)),(0,0,1,(256,1)),(255,0,1,(511,0)),
                 (0x55,0xaa,2,(255,0)),(0x55,0xaa,3,(0,1))]
        for a,b,op,expected in cases:
            self.assertEqual(reference(a,b,op),expected)

    def test_test_vectors_cover_modes_and_walking_bits(self):
        vectors = test_vectors()
        self.assertEqual(vectors,test_vectors())
        self.assertEqual({v['op'] for v in vectors},{0,1,2,3})
        combinations = {(v['a'],v['b'],v['op']) for v in vectors}
        for i in range(8):
            for j in range(8):
                for op in range(4):
                    self.assertIn((1<<i,1<<j,op),combinations)
        self.assertEqual(vectors[-1]['a'],0)
        self.assertEqual(vectors[-1]['b'],0)

    def test_synthesized_netlist_matches_reference(self):
        path = Path(__file__).resolve().parents[1]/'output'/'alu8.json'
        if not path.exists():
            self.skipTest('Run make TOP=alu8 first')
        vectors = test_vectors()
        self.assertEqual(verify_netlist(path,vectors),len(vectors))

    def test_xnor_has_a_real_output_inverter(self):
        ic = IntermediateCircuit()
        xor = ic.gen_gate(Vertex('xor',VertexType.FUNCTION,func_type='XOR2'))
        for kind in ('XNOR','XNOR2','$_XNOR_'):
            xnor = ic.gen_gate(Vertex('xnor',VertexType.FUNCTION,func_type=kind))
            x,y = xnor.pin_positions(True)[0]
            self.assertEqual(xnor.blocks[(x,y,xnor.size_z-1)],
                             'minecraft:redstone_wall_torch[facing=south]')
            self.assertEqual(xnor.blocks[(x,y,xnor.size_z-2)],'minecraft:white_wool')
            self.assertTrue(all(xnor.blocks[p] == b for p,b in xor.blocks.items()))

    def test_large_fill_commands_cover_volume_without_exceeding_cap(self):
        low,high,origin = (-1,-1,-1),(130,9,400),(-479,-60,480)
        commands = fill_commands(low,high,origin)
        volume = 0
        boxes = []
        for command in commands:
            tokens = command.split()
            a,b = tuple(map(int,tokens[1:4])),tuple(map(int,tokens[4:7]))
            count = (b[0]-a[0]+1)*(b[1]-a[1]+1)*(b[2]-a[2]+1)
            self.assertLessEqual(count,32768)
            self.assertTrue(all(low[i]+origin[i] <= a[i] <= b[i] <= high[i]+origin[i]
                                for i in range(3)))
            for c,d in boxes:
                self.assertTrue(any(b[i] < c[i] or d[i] < a[i] for i in range(3)))
            boxes.append((a,b))
            volume += count
        self.assertEqual(volume,132*11*402)


if __name__ == '__main__':
    unittest.main()
