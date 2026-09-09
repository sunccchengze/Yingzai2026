import sys, bpy
f   = sys.argv[1] if len(sys.argv) > 1 else "小鹰3D模型/展翅写实版_小鹰/小鹰_3D.blend"
out = sys.argv[2] if len(sys.argv) > 2 else "小鹰3D模型/展翅写实版_小鹰/preview.png"
bpy.ops.wm.open_mainfile(filepath=f)
scn = bpy.context.scene
scn.render.engine = 'CYCLES'
scn.cycles.device = 'CPU'
scn.cycles.samples = 60
scn.cycles.use_denoising = True
scn.render.resolution_x = 1000
scn.render.resolution_y = 1250
scn.render.filepath = out
bpy.ops.render.render(write_still=True)
print("DONE", out)
