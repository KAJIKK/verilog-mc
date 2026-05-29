# Variables
LIB_FILE = my_gates.lib
OUT_DIR = output

# Default top module
TOP = multiplexer4_1

# Files
# Search in current dir or tests/
VERILOG_FILE = $(shell find . -name "$(TOP).v")
OUTPUT_JSON = $(OUT_DIR)/$(TOP).json
OUTPUT_PREFIX = $(OUT_DIR)/$(TOP)

# Default target
all: prep synth

# Ensure output directory exists
prep:
	mkdir -p $(OUT_DIR)

# Unified Synthesis Pipeline
# - flatten: Inlines any submodules into the top module so we have one graph.
# - abc -liberty: Maps combinational logic securely to our specific Minecraft gates.
synth: prep $(VERILOG_FILE)
	yosys -p "read_verilog $(VERILOG_FILE); \
	          hierarchy -check -top $(TOP); \
	          flatten; \
	          proc; opt; \
	          synth -top $(TOP); \
	          abc -liberty $(LIB_FILE); \
	          opt; clean; \
	          json -o $(OUTPUT_JSON)"

# Visualization
viz: synth
	yosys -p "read_liberty -lib $(LIB_FILE); \
	          read_json $(OUTPUT_JSON); \
	          splitnets -ports; \
	          show -format svg -prefix $(OUTPUT_PREFIX)"

# Clean target
clean:
	rm -rf $(OUT_DIR)
	rm -f abc.history
