"""Geometry and power-source regressions for the isolated orientation probe."""
import json
from pathlib import Path
import tempfile
import unittest

from intermediate_circuit import IntermediateCircuit
from logic_gates import Gate, LogicGates
from netlist_parser import Vertex, VertexType
from tests.benchmark_orientation import OrientedCircuit, reverse_gate


class GateOrientationTests(unittest.TestCase):
    def test_rotation_is_involutive_and_preserves_named_pin_roles(self):
        for gate in (LogicGates.d_latch(),LogicGates.sr_latch(),LogicGates.t_latch(),
                     LogicGates.xor_gate(),LogicGates.nand_gate(2)):
            with self.subTest(size=(gate.size_x,gate.size_y,gate.size_z)):
                rotated = reverse_gate(gate)
                restored = reverse_gate(rotated)
                self.assertEqual(restored.blocks,gate.blocks)
                for as_out in (False,True):
                    self.assertEqual(restored.pin_positions(as_out),gate.pin_positions(as_out))
                if isinstance(gate.input_offsets,dict):
                    self.assertEqual(list(rotated.input_offsets),list(gate.input_offsets))
                if isinstance(gate.output_offsets,dict):
                    self.assertEqual(list(rotated.output_offsets),list(gate.output_offsets))

    def test_wire_connection_properties_rotate_with_components(self):
        gate = Gate(3,1,2,1,1)
        gate.set_block(0,0,0,'minecraft:redstone_wire[north=up,east=side]')
        gate.set_block(2,0,1,'minecraft:repeater[facing=west,delay=2]')
        rotated = reverse_gate(gate)
        self.assertEqual(rotated.blocks[(2,0,1)],'minecraft:redstone_wire[south=up,west=side]')
        self.assertEqual(rotated.blocks[(0,0,0)],'minecraft:repeater[facing=east,delay=2]')

    def test_source_starts_before_padding_for_both_orientations(self):
        for backwards in (False,True):
            with self.subTest(backwards=backwards):
                ic = OrientedCircuit.__new__(OrientedCircuit)
                IntermediateCircuit.__init__(ic)
                v = Vertex('gate',VertexType.FUNCTION,func_type='NAND2',bits=[2])
                dummy = Vertex('padding',VertexType.FUNCTION,func_type='PADDING')
                gate = LogicGates.nand_gate(2)
                gate = reverse_gate(gate) if backwards else gate
                gate.x_offset = 0
                padding = Gate(1,1,5,0,0)
                padding.x_offset = 6
                ic.vertex_layers = [[v,dummy]]
                ic.gate_layers = [[gate,padding]]
                ic.gates = {v:gate,dummy:padding}
                ic.reversed = {v} if backwards else set()
                ic.feeds = set()
                circuit,sources,_ = ic.assemble()
                expected = ((2,0,1),15,'north') if backwards else ((0,0,3),15,'south')
                self.assertEqual(sources,[expected])
                # Two extension dust blocks follow the true power origin.
                self.assertTrue(all(p in circuit.blocks for p in circuit.routing_positions))
                self.assertEqual(len(circuit.routing_positions),2)

    def test_reverse_latch_requires_real_feedthroughs(self):
        data = {'modules':{'latch':{
            'ports':{'d':{'direction':'input','bits':[2]},
                     'e':{'direction':'input','bits':[3]},
                     'q':{'direction':'output','bits':[4]}},
            'cells':{'cell':{'type':'$_DLATCH_P_',
                             'connections':{'D':[2],'E':[3],'Q':[4]}}}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'latch.json'
            path.write_text(json.dumps(data))
            rows = [['d','e'],['cell'],['q']]
            forward = OrientedCircuit(path,rows,set())
            reverse = OrientedCircuit(path,rows,{'cell'})
            self.assertEqual(len(forward.feeds),0)
            self.assertEqual(len(reverse.feeds),3)
            self.assertEqual(sorted(v.bits for v in reverse.feeds),[[2],[3],[4]])
            reverse.route_oriented()
            circuit,sources,_ = reverse.assemble()
            self.assertTrue(circuit.routing_positions)
            self.assertTrue(any(direction == 'north' for _,_,direction in sources))
            self.assertEqual({bit for v in reverse.feeds for bit in v.bits},{2,3,4})


if __name__ == '__main__':
    unittest.main()
