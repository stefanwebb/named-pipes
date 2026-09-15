"""Build a Unity-compatible skinned FBX for Ardy's cskel27 skeleton.

Run inside Blender (headless):
    /Applications/Blender.app/Contents/MacOS/Blender -b --python build_fbx.py -- cskel27.json skin_standard.npz cskel27.fbx

cskel27.json      joint names + parents (dumped from ardy.skeleton.CoreSkeleton27)
skin_standard.npz Ardy's viz skin: bind mesh, LBS weights, bind joint transforms
                  (ardy/assets/skeletons/cskel27/, used by ardy.viz.core_skin.CoreSkin)

Bone heads are placed at the bind-pose joint positions (T-pose, feet on the
ground, pelvis at y=0.97 m) so the mesh binds with no re-posing.
"""
import json
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
json_path, npz_path, dst = argv
data = json.load(open(json_path))
skin = np.load(npz_path)

joints = data["joints"]
names = [j["name"] for j in joints]
assert names == list(skin["rig_joint_names"]), "joint order in json and npz differ"
by_name = {j["name"]: j for j in joints}
children = {n: [] for n in names}
for j in joints:
    if j["parent"]:
        children[j["parent"]].append(j["name"])

bind_pos = skin["bind_rig_transform"][:, :3, 3]  # [27, 3] metres, Y-up

# Ardy is Y-up / +Z forward; Blender is Z-up / -Y forward.  (x, y, z)_ardy -> (x, -z, y)_blender
def to_blender(p):
    x, y, z = (float(v) for v in p)
    return Vector((x, -z, y))

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0

# ---- armature ----
arm_data = bpy.data.armatures.new(data["name"])
arm_obj = bpy.data.objects.new(data["name"], arm_data)
scene.collection.objects.link(arm_obj)
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode="EDIT")

LEAF_LEN = 0.05
PREFERRED_TAIL = {"Hips": "Spine", "Spine3": "Neck", "RightHand": "RightHandEnd", "LeftHand": "LeftHandEnd"}
pos = {n: to_blender(bind_pos[i]) for i, n in enumerate(names)}

ebones = {}
for j in joints:
    name = j["name"]
    head = pos[name]
    kids = children[name]
    if kids:
        tail = pos[PREFERRED_TAIL.get(name, kids[0])]
    else:
        d = head - pos[j["parent"]]
        tail = head + (d.normalized() * LEAF_LEN if d.length > 1e-6 else Vector((0, 0, LEAF_LEN)))
    if (tail - head).length < 1e-4:
        tail = head + Vector((0, 0, LEAF_LEN))
    eb = arm_data.edit_bones.new(name)
    eb.head, eb.tail = head, tail
    ebones[name] = eb
for j in joints:
    if j["parent"]:
        eb = ebones[j["name"]]
        eb.parent = ebones[j["parent"]]
        eb.use_connect = (eb.head - eb.parent.tail).length < 1e-4
bpy.ops.object.mode_set(mode="OBJECT")

# ---- skinned mesh ----
verts = [to_blender(v) for v in skin["bind_vertices"]]
faces = [tuple(int(i) for i in f) for f in skin["faces"]]
mesh = bpy.data.meshes.new("cskel27_skin")
mesh.from_pydata(verts, [], faces)
mesh.validate()
mesh.update()
mesh_obj = bpy.data.objects.new("cskel27_skin", mesh)
scene.collection.objects.link(mesh_obj)

# one vertex group per joint, weights straight from the LBS tables
groups = [mesh_obj.vertex_groups.new(name=n) for n in names]
lbs_idx, lbs_w = skin["lbs_indices"], skin["lbs_weights"]
for v in range(len(verts)):
    for k in range(lbs_idx.shape[1]):
        w = float(lbs_w[v, k])
        if w > 0.0:
            groups[int(lbs_idx[v, k])].add([v], w, "REPLACE")

mesh_obj.parent = arm_obj
mod = mesh_obj.modifiers.new("Armature", "ARMATURE")
mod.object = arm_obj

# smooth shading
for p in mesh.polygons:
    p.use_smooth = True

bpy.ops.export_scene.fbx(
    filepath=dst,
    use_selection=False,
    object_types={"ARMATURE", "MESH"},
    apply_unit_scale=True,
    apply_scale_options="FBX_SCALE_ALL",
    axis_forward="-Z",
    axis_up="Y",
    add_leaf_bones=False,
    bake_anim=False,
    armature_nodetype="NULL",
    use_armature_deform_only=False,
    mesh_smooth_type="FACE",
    use_mesh_modifiers=False,   # keep the mesh in bind pose, skinning stays live in Unity
)
print(f"wrote {dst}: {len(arm_data.bones)} bones, {len(verts)} verts, {len(faces)} faces")
