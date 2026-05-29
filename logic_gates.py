import json
import os

class Circuit:
    def __init__(self, size_x, size_y, size_z):
        self.size_x = size_x
        self.size_y = size_y
        self.size_z = size_z
        self.blocks = {} # (x, y, z) -> block_string

    def set_block(self, x, y, z, block):
        self.blocks[(x, y, z)] = block
        
class Gate(Circuit):
    def __init__(self, size_x, size_y, size_z, num_inputs, num_outputs, input_spacing=1, output_spacing=1, output_lines=None):
        super().__init__(size_x, size_y, size_z)
        self.num_inputs = num_inputs
        self.num_outputs = num_outputs
        self.input_spacing = input_spacing
        self.output_spacing = output_spacing
        self.output_lines = output_lines or [0]
        self.is_io = False
        self.input_offsets = None
        self.output_offsets = None

class LogicGates:
    _library = {}
    
    @staticmethod
    def load_library(filepath="gates.json"):
        if not os.path.exists(filepath):
            return
        with open(filepath, "r") as f:
            LogicGates._library = json.load(f)

    @staticmethod
    def get_gate(gate_name):
        if not LogicGates._library:
            LogicGates.load_library()
        
        data = LogicGates._library.get(gate_name)
        if not data:
            return None
            
        sx, sy, sz = data["size"]
        gate = Gate(sx, sy, sz, data["num_inputs"], data["num_outputs"])
        gate.input_offsets = data.get("input_offsets")
        gate.output_offsets = data.get("output_offsets")
        
        for pos_str, block in data["blocks"].items():
            x, y, z = map(int, pos_str.split(","))
            gate.set_block(x, y, z, block)
            
        return gate

    @staticmethod
    def input_gate(id_str):
        gate = Gate(1, 2, 1, 1, 1, 0, 0, [0])
        gate.is_io = True
        gate.set_block(0, 0, 0, "minecraft:white_wool")
        
        # New 1.20+ front_text format
        msg = f"'[{{\"text\":\"{id_str}\"}}]'"
        empty = "'[{\"text\":\"\"}]'"
        sign_nbt = f"{{front_text:{{messages:[{empty},{msg},{empty},{empty}]}}}}"        
        gate.set_block(0, 1, 0, f"minecraft:oak_sign[rotation=8]{sign_nbt}")
        return gate

    @staticmethod
    def output_gate(id_str):
        gate = Gate(1, 2, 1, 1, 1, 0, 0, [0])
        gate.is_io = True
        gate.set_block(0, 0, 0, "minecraft:redstone_lamp")
        
        msg = f"'[{{\"text\":\"{id_str}\"}}]'"
        empty = "'[{\"text\":\"\"}]'"
        sign_nbt = f"{{front_text:{{messages:[{empty},{msg},{empty},{empty}]}}}}"        
        gate.set_block(0, 1, 0, f"minecraft:oak_sign[rotation=0]{sign_nbt}")
        return gate

    @staticmethod
    def _not():
        return LogicGates.get_gate("NOT")

    @staticmethod
    def relay():
        return LogicGates.get_gate("RELAY")

    @staticmethod
    def xor_gate():
        return LogicGates.get_gate("XOR")

    @staticmethod
    def mux_gate():
        return LogicGates.get_gate("MUX")

    @staticmethod
    def and_gate(inputs):
        # Procedural generation for variable-input AND gates
        if inputs == 0:
            raise ValueError("Gate cannot have 0 inputs")
        width = 1 if inputs == 1 else (inputs * 2) - 1
        gate = Gate(width, 2, 3, inputs, 1, 1, 0, [0])

        for i in range(width):
            if i % 2 == 0:
                gate.set_block(i, 0, 0, "minecraft:white_wool")
                gate.set_block(i, 1, 0, "minecraft:redstone_torch")
            gate.set_block(i, 0, 1, "minecraft:white_wool")
            gate.set_block(i, 1, 1, "minecraft:redstone_wire")

        gate.set_block(0, 0, 2, "minecraft:redstone_wall_torch[facing=south]")
        return gate

    @staticmethod
    def nand_gate(inputs):
        # NAND is just an AND without the final inverter
        if inputs == 0:
            raise ValueError("Gate cannot have 0 inputs")
        width = 1 if inputs == 1 else (inputs * 2) - 1
        gate = Gate(width, 2, 2, inputs, 1, 1, 0, [0])
        
        for i in range(width):
            if i % 2 == 0:
                gate.set_block(i, 0, 0, "minecraft:white_wool")
                gate.set_block(i, 1, 0, "minecraft:redstone_torch")
            gate.set_block(i, 0, 1, "minecraft:white_wool")
            gate.set_block(i, 1, 1, "minecraft:redstone_wire")
        return gate

    @staticmethod
    def or_gate(inputs):
        if inputs == 0:
            raise ValueError("Gate cannot have 0 inputs")
        width = 1 if inputs == 1 else (inputs * 2) - 1
        gate = Gate(width, 1, 2, inputs, 1, 1, 0, [0])

        for i in range(width):
            if i % 2 == 0:
                gate.set_block(i, 0, 0, "minecraft:repeater[facing=north]")
            gate.set_block(i, 0, 1, "minecraft:redstone_wire")
        return gate

    @staticmethod
    def nor_gate(inputs):
        # NOR is OR + Inverter
        if inputs == 0:
            raise ValueError("Gate cannot have 0 inputs")
        width = 1 if inputs == 1 else (inputs * 2) - 1
        gate = Gate(width, 1, 3, inputs, 1, 1, 0, [0])
        
        for i in range(width):
            if i % 2 == 0:
                gate.set_block(i, 0, 0, "minecraft:repeater[facing=north]")
            gate.set_block(i, 0, 1, "minecraft:redstone_wire")

        gate.set_block(0, 0, 1, "minecraft:white_wool")
        gate.set_block(0, 0, 2, "minecraft:redstone_wall_torch[facing=south]")
        return gate
