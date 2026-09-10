import sys, bpy, mathutils
f = sys.argv[1]
bpy.ops.wm.open_mainfile(filepath=f)
objs = [o for o in bpy.data.objects if o.type == 'MESH']
mins = [1e9]*3; maxs = [-1e9]*3
import collections
groups = collections.defaultdict(list)
for o in objs:
    try:
        m = o.matrix_world
    except Exception as e:
        m = None
    if m is None:
        continue
    for c in o.bound_box:
        w = m @ mathutils.Vector(c)
        for i in range(3):
            mins[i]=min(mins[i],w[i]); maxs[i]=max(maxs[i],w[i])
    # classify by name keyword
    key = o.name[:2]
    for kw,grp in [('翼','wing'),('尾','tail'),('头','head'),('喙','beak'),
                   ('眼','eye'),('腿','leg'),('趾','toe'),('体','body'),('身','body')]:
        if o.name.startswith(kw):
            groups.setdefault(grp, []).append(o); break
print("mesh_objects", len(objs))
print("bbox min",[round(x,2) for x in mins],"max",[round(x,2) for x in maxs])
for grp, os_ in groups.items():
    gmin=[1e9]*3; gmax=[-1e9]*3
    for o in os_:
        m=o.matrix_world
        for c in o.bound_box:
            w=m@mathutils.Vector(c)
            for i in range(3):
                gmin[i]=min(gmin[i],w[i]); gmax[i]=max(gmax[i],w[i])
    print(f"{grp:5s} n={len(os_):3d}  x[{gmin[0]:.2f},{gmax[0]:.2f}] y[{gmin[1]:.2f},{gmax[1]:.2f}] z[{gmin[2]:.2f},{gmax[2]:.2f}]")
