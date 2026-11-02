"""Small runtime helpers shared by generated Minecraft test packs."""
import re


def install_chunk_lease(write,namespace,low,high):
    """Acquire only missing forced-load flags and release only acquired flags.

    Repeated load/start calls keep existing ownership; pre-existing forced
    chunks are never marked owned. unload is safe to call more than once.
    """
    if not re.fullmatch(r'[a-z0-9_]{1,16}',namespace):
        raise ValueError('Invalid test namespace')
    if any(low[i] > high[i] for i in (0,2)):
        raise ValueError('Invalid chunk bounds')
    chunks = [(x,z) for x in range(low[0]//16,high[0]//16+1)
              for z in range(low[2]//16,high[2]//16+1)]
    load,unload = [],[]
    for i,(x,z) in enumerate(chunks):
        key = f'x{"m"+str(-x) if x < 0 else x}_z{"m"+str(-z) if z < 0 else z}'
        owned = f'owned.{key}'
        load.append(f'execute unless data storage {namespace}:leases {owned} run function {namespace}:lease_{i}')
        write(f'lease_{i}',[
            f'data modify storage {namespace}:leases probe set value 0b',
            f'execute store success storage {namespace}:leases probe byte 1 run forceload query {x*16} {z*16}',
            f'execute if data storage {namespace}:leases {{probe:0b}} run forceload add {x*16} {z*16}',
            f'execute if data storage {namespace}:leases {{probe:0b}} run data modify storage {namespace}:leases {owned} set value 1b'])
        unload.append(f'execute if data storage {namespace}:leases {owned} run forceload remove {x*16} {z*16}')
    unload.append(f'data remove storage {namespace}:leases owned')
    write('load',load)
    write('unload',unload)
    return len(chunks)


def install_case_dispatch(write,namespace,count):
    """Constant-size dispatch instead of scanning all case numbers each time."""
    if count < 1:
        raise ValueError('At least one case is required')
    write('dispatch',[f'$function {namespace}:apply_$(case)'])
    commands = [f'execute store result storage {namespace}:dispatch case int 1 run scoreboard players get #case {namespace}']
    if count > 1:
        commands.append(f'execute if score #case {namespace} matches 1..{count-1} run function {namespace}:dispatch with storage {namespace}:dispatch')
    commands.append(f'execute if score #case {namespace} matches {count} run function {namespace}:finish')
    return commands
