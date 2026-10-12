import mcschematic

schem = mcschematic.MCSchematic()
# 1.18.2 format for sign text
sign_block = 'minecraft:oak_sign[rotation=8]{Text1:\'{"text":"my_input"}\',Text2:\'{"text":""}\',Text3:\'{"text":""}\',Text4:\'{"text":""}\'}'
schem.setBlock((0, 0, 0), sign_block)
schem.save(".", "test_sign", mcschematic.Version.JE_1_18_2)
print("Done")
