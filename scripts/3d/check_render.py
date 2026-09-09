import sys
import bpy
f = sys.argv[1] if len(sys.argv) > 1 else "小鹰3D模型/小鹰_3D.blend"
out = sys.argv[2] if len(sys.argv) > 2 else "/home/user/_check.png"
bpy.ops.wm.open_mainfile(filepath=f)
scn = bpy.context.scene
scn.render.engine = 'CYCLES'
scn.cycles.samples = 12
scn.render.resolution_x = 560
scn.render.resolution_y = 640
scn.render.filepath = out
bpy.ops.render.render(write_still=True)
print("DONE", out)
