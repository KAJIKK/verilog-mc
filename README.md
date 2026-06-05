# Verilog to Minecraft (verilog-mc)

A compiler toolchain that translates Verilog hardware descriptions into functional Minecraft redstone circuits.

## Overview

`verilog-mc` leverages the industry-standard synthesis tool **Yosys** to compile Verilog code into a gate-level netlist. This netlist is then mapped to a custom library of Minecraft logic gates and automatically laid out and routed into a `.schem` file, ready to be imported into Minecraft via WorldEdit.

### Key Features

- **Verilog Synthesis:** Uses Yosys to process Verilog, supporting standard logic constructs.
- **Custom Gate Library:** Maps logic to compact, Redstone-efficient gate designs (AND, OR, XOR, MUX, etc.).
- **Automatic Routing:** Handles complex wire routing between gates.
- **Signal Post-Processing:** Automatically places repeaters on long redstone lines to prevent signal loss.
- **Carry Cancel Adder Support:** Includes high-performance adder architectures (like CCA) optimized for Minecraft's redstone tick system.
- **Visualization:** Generate SVG diagrams of the synthesized logic netlists.

## Project Structure

- `*.v`: Verilog source files (e.g., `adder32_cca.v`, `multiplexer4_1.v`).
- `my_gates.lib`: Liberty library file defining the gate primitives for Yosys.
- `gates.json`: Physical layout and block definitions for each gate in Minecraft.
- `generate_schem.py`: The main script to generate a Minecraft schematic from a synthesized netlist.
- `repeater_postprocessor.py`: A graph-based tool to optimize repeater placement for all signal sources.
- `router.py`: Logic for routing redstone signals between gates.
- `Makefile`: Orchestrates the synthesis and visualization pipeline.

## Prerequisites

- **Yosys:** Open Source Synthesis Suite.
- **Python 3.10+**
- **mcschematic:** Python library for generating Minecraft schematics.
- **nbtlib:** NBT parsing library.
- **Graphviz (Optional):** For netlist visualization.

## Usage

### 1. Synthesis

To synthesize your Verilog code into a JSON netlist:

```bash
make TOP=your_module_name
```

Replace `your_module_name` with the name of your Verilog module. The output will be stored in `output/your_module_name.json`.

### 2. Schematic Generation

Convert the synthesized netlist into a Minecraft schematic:

```bash
python3 generate_schem.py output/your_module_name.json
```

This will generate `your_module_name.schem` in the current directory and automatically attempt to copy it to your Minecraft WorldEdit schematics folder.

### 3. Visualization

To view the synthesized gate-level logic:

```bash
make viz TOP=your_module_name
```

This generates an SVG file in the `output/` directory.

## Performance Optimization: Carry Cancel Adder (CCA)

For high-speed arithmetic, use the provided `adder32_cca.v`. This implementation uses a Carry Cancel architecture that maps directly to the multiplexer primitives in the custom library, allowing for "instant-carry" redstone behavior across large bit-widths.

## Acknowledgments

- **Yosys** for the synthesis engine.
- **mcschematic** for the Minecraft integration.
- The Redstone engineering community for high-speed gate designs.
