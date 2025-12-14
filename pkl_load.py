# pkl_load.py

import bpy
import os
import pickle
import numpy as np
from mathutils import Matrix, Vector
from bpy.app.translations import pgettext_iface as iface_

from . import bones_list

# -----------------------------
# Translations
# -----------------------------
_TRANSLATIONS = {
    "ja_JP": {
        ("*", "Inputs"): "入力",
        ("*", "Settings"): "設定",
        ("*", "Run"): "実行",
        ("*", "Height"): "高さ",
        ("*", "Fit to Animation Length"): "アニメーション長に合わせる",
    }
}

# Use a stable addon key across reloads
_ADDON_KEY = __package__ or __name__.split(".")[0]

# -----------------------------
# Utilities
# -----------------------------
def _popup_jp(context, title, message):
    def _draw(self, _ctx):
        self.layout.label(text=message)
    context.window_manager.popup_menu(_draw, title=title, icon="INFO")


def _armature_poll(self, obj):
    return obj is not None and obj.type == "ARMATURE"


def _get_source_armature(context):
    return context.scene.pkl_loader_source_armature


def _ensure_active_selected(obj):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


# -----------------------------
# Bones List cache
# -----------------------------
class PKL_BoneMapItem(bpy.types.PropertyGroup):
    smpl: bpy.props.StringProperty(name="SMPL")
    pmx: bpy.props.StringProperty(name="PMX")


class PKL_UL_BoneMap(bpy.types.UIList):
    # Two columns: SMPL / PMX
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        split = layout.split(factor=0.5)
        # NOT translate bone names
        split.label(text=item.smpl or "", translate=False)
        split.label(text=item.pmx or "", translate=False)


def _populate_bones_cache():
    try:
        wm = bpy.context.window_manager
    except Exception:
        return None

    col = wm.pkl_loader_bones
    if len(col) == 0:
        for smpl, pmx in bones_list.iter_bone_pairs():
            it = col.add()
            it.smpl = smpl
            it.pmx = pmx
    return None


def _schedule_populate_bones_cache():
    try:
        bpy.app.timers.register(_populate_bones_cache, first_interval=0.1)
    except Exception:
        pass


@bpy.app.handlers.persistent
def _pkl_loader_on_load_post(_dummy):
    _schedule_populate_bones_cache()


# -----------------------------
# PKL_load
# -----------------------------
def _resolve_bone_name(arm_ob, key):
    smpl, pmx = bones_list.PART_MATCH_CUSTOM_LESS2[key]
    if smpl in arm_ob.pose.bones:
        return smpl
    if pmx in arm_ob.pose.bones:
        return pmx
    raise KeyError(f'Bone "{smpl}" or "{pmx}" not found for key "{key}"')


def _Rodrigues_old(rotvec):
    theta = np.linalg.norm(rotvec)
    r = (rotvec / theta).reshape(3, 1) if theta > 0.0 else rotvec
    cost = np.cos(theta)
    mat = np.asarray(
        [
            [0, -r[2], r[1]],
            [r[2], 0, -r[0]],
            [-r[1], r[0], 0],
        ],
        dtype=object,
    )
    return cost * np.eye(3) + (1 - cost) * r.dot(r.T) + np.sin(theta) * mat


def _rodrigues2mrots_22(pose22x3):
    rod_rots = np.asarray(pose22x3).reshape(22, 3)
    return [_Rodrigues_old(rod_rot) for rod_rot in rod_rots]


def _apply_motion_pklload0_style(context, arm_ob, results, height, fit_timeline: bool):
    arm_ob.animation_data_clear()

    qtd_frames = len(results["smpl_params_global"]["transl"])
    print(f"Loading {qtd_frames} frames")

    # Fit timeline to animation length
    if fit_timeline and qtd_frames > 0:
        scn = context.scene
        scn.frame_start = 0
        scn.frame_end = max(0, qtd_frames - 1)

    root_name = _resolve_bone_name(arm_ob, "root")
    pelvis_name = _resolve_bone_name(arm_ob, "bone_00")

    for fframe in range(0, qtd_frames):
        context.scene.frame_set(fframe)

        trans = results["smpl_params_global"]["transl"][fframe]
        global_orient = results["smpl_params_global"]["global_orient"][fframe]
        body_pose = results["smpl_params_global"]["body_pose"][fframe]

        body_pose_fim = body_pose.reshape(int(len(body_pose) / 3), 3)
        final_body_pose = np.vstack([global_orient, body_pose_fim])  # 22x3

        mrots = _rodrigues2mrots_22(final_body_pose)

        # Location on pelvis
        trans_v = Vector((trans[0], trans[1] - height, trans[2]))
        arm_ob.pose.bones[pelvis_name].location = trans_v
        arm_ob.pose.bones[pelvis_name].keyframe_insert("location", frame=fframe)

        # Root fixed (Z 180 deg)
        rb = arm_ob.pose.bones[root_name]
        rb.rotation_mode = "QUATERNION"
        rb.rotation_quaternion = (0, 0, 1, 0)

        # Apply 22 rotations to bone_00..bone_21
        for ibone, mrot in enumerate(mrots):
            if ibone >= 22:
                break
            key = f"bone_{ibone:02d}"
            bone_name = _resolve_bone_name(arm_ob, key)
            bone = arm_ob.pose.bones[bone_name]
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = Matrix(mrot).to_quaternion()
            bone.keyframe_insert("rotation_quaternion", frame=fframe)

        context.view_layer.update()


# -----------------------------
# Operators
# -----------------------------
class PKLLOADER_OT_set_source_pkl(bpy.types.Operator):
    """DnD: set Source PKL path without opening file browser"""
    bl_idname = "pkl_loader.set_source_pkl"
    bl_label = "Set Source PKL"
    bl_options = {"INTERNAL"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        if self.filepath and self.filepath.lower().endswith(".pkl"):
            context.scene.pkl_loader_source_pkl = self.filepath
        return {"FINISHED"}


class PKLLOADER_OT_apply_animation(bpy.types.Operator):
    bl_idname = "pkl_loader.apply_animation"
    bl_label = "Apply Animation"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm_ob = _get_source_armature(context)
        pkl_path = context.scene.pkl_loader_source_pkl

        if (arm_ob is None) or (not pkl_path) or (arm_ob.type != "ARMATURE"):
            _popup_jp(context, "PKL Loader", "ソースデータが不足しています。")
            return {"CANCELLED"}

        abs_path = bpy.path.abspath(pkl_path)
        if not os.path.isfile(abs_path):
            _popup_jp(context, "PKL Loader", "ソースデータが不足しています。")
            return {"CANCELLED"}

        with open(abs_path, "rb") as f:
            data = pickle.load(f)

        results = data.get("results", data) if isinstance(data, dict) else data

        try:
            _ensure_active_selected(arm_ob)
            bpy.ops.object.mode_set(mode="POSE")
            _apply_motion_pklload0_style(
                context,
                arm_ob,
                results,
                context.scene.pkl_loader_height,
                context.scene.pkl_loader_fit_timeline,
            )
        finally:
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        return {"FINISHED"}


class PKLLOADER_OT_clean_animation(bpy.types.Operator):
    bl_idname = "pkl_loader.clean_animation"
    bl_label = "Clean Animation"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm_ob = _get_source_armature(context)
        if arm_ob is None or arm_ob.type != "ARMATURE":
            _popup_jp(context, "PKL Loader", "削除するアニメーションデータはありません。")
            return {"CANCELLED"}

        # Make it active to ensure consistent behavior
        try:
            _ensure_active_selected(arm_ob)
        except Exception:
            pass

        # Keep a reference to the current Action so we can delete it if unused after clearing
        ad = arm_ob.animation_data
        act = ad.action if (ad and ad.action) else None

        # 1) Remove animation data (Action/NLA links)
        arm_ob.animation_data_clear()

        # 2) Reset current pose to Rest Pose (clear pose transforms)
        # Direct data edits are the most reliable across contexts.
        try:
            # Pose mode is preferable (some rigs update more reliably),
            # but even if this fails, direct edits below still work.
            bpy.ops.object.mode_set(mode="POSE")
        except Exception:
            pass

        try:
            for pb in arm_ob.pose.bones:
                pb.location = (0.0, 0.0, 0.0)
                pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                pb.scale = (1.0, 1.0, 1.0)
                pb.matrix_basis = Matrix.Identity(4)
            context.view_layer.update()
        except Exception:
            pass

        # Also try Blender's built-in clear operators (if available in this context).
        try:
            bpy.ops.pose.select_all(action="SELECT")
            bpy.ops.pose.loc_clear()
            bpy.ops.pose.rot_clear()
            bpy.ops.pose.scale_clear()
        except Exception:
            pass

        # Back to Object mode
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

        # 3) Remove the old Action datablock if nothing else is using it
        if act is not None and act.users == 0:
            try:
                bpy.data.actions.remove(act)
            except Exception:
                pass

        # Optional: jump to start frame so the viewport shows a clean state
        try:
            context.scene.frame_set(context.scene.frame_start)
        except Exception:
            pass

        return {"FINISHED"}


class PKLLOADER_OT_export_bvh(bpy.types.Operator):
    bl_idname = "pkl_loader.export_bvh"
    bl_label = "Export BVH"
    bl_options = {"REGISTER"}

    def execute(self, context):
        arm_ob = _get_source_armature(context)
        if arm_ob is None or arm_ob.type != "ARMATURE":
            _popup_jp(context, "PKL Loader", "ソースデータが不足しています。")
            return {"CANCELLED"}
        _ensure_active_selected(arm_ob)
        bpy.ops.export_anim.bvh("INVOKE_DEFAULT")
        return {"FINISHED"}


class PKLLOADER_OT_export_fbx(bpy.types.Operator):
    bl_idname = "pkl_loader.export_fbx"
    bl_label = "Export FBX"
    bl_options = {"REGISTER"}

    def execute(self, context):
        arm_ob = _get_source_armature(context)
        if arm_ob is None or arm_ob.type != "ARMATURE":
            _popup_jp(context, "PKL Loader", "ソースデータが不足しています。")
            return {"CANCELLED"}
        _ensure_active_selected(arm_ob)
        bpy.ops.export_scene.fbx("INVOKE_DEFAULT")
        return {"FINISHED"}


# -----------------------------
# FileHandler
# -----------------------------
class PKLLOADER_FH_PKL(bpy.types.FileHandler):
    bl_idname = "PKLLOADER_FH_PKL"
    bl_label = "PKL Loader"
    bl_import_operator = "pkl_loader.set_source_pkl"
    bl_file_extensions = ".pkl"

    @classmethod
    def poll_drop(cls, context):
        try:
            return (
                context is not None
                and context.scene is not None
                and context.area
                and context.area.type == "VIEW_3D"
            )
        except Exception:
            return False


# -----------------------------
# UI
# -----------------------------
class PKLLOADER_PT_panel(bpy.types.Panel):
    bl_label = "PKL Loader"
    bl_idname = "PKLLOADER_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "PKL Loader"

    def draw(self, context):
        layout = self.layout
        scn = context.scene
        wm = context.window_manager

        # INPUTS foldout
        row = layout.row(align=True)
        row.alignment = "LEFT"
        row.prop(
            scn, "pkl_loader_tab_inputs",
            text=iface_("Inputs"),
            emboss=False,
            icon=("TRIA_DOWN" if scn.pkl_loader_tab_inputs else "TRIA_RIGHT"),
        )
        if scn.pkl_loader_tab_inputs:
            col = layout.column(align=True)
            col.label(text="Source Armature:")
            col.prop(scn, "pkl_loader_source_armature", text="")
            col.label(text="Source PKL:")
            col.prop(scn, "pkl_loader_source_pkl", text="")

        # SETTINGS foldout
        row = layout.row(align=True)
        row.alignment = "LEFT"
        row.prop(
            scn, "pkl_loader_tab_settings",
            text=iface_("Settings"),
            emboss=False,
            icon=("TRIA_DOWN" if scn.pkl_loader_tab_settings else "TRIA_RIGHT"),
        )
        if scn.pkl_loader_tab_settings:
            col = layout.column(align=True)

            # Fit to animation length (translated)
            col.prop(scn, "pkl_loader_fit_timeline", text=iface_("Fit to Animation Length"))

            col.prop(scn, "pkl_loader_height", text=iface_("Height"))

            col.label(text="Bones List")  # not translate
            hdr = col.row(align=True)
            split = hdr.split(factor=0.5)
            split.label(text="SMPL Bones:", translate=False)
            split.label(text="PMX Bones:", translate=False)

            col.template_list(
                "PKL_UL_BoneMap", "",
                wm, "pkl_loader_bones",
                wm, "pkl_loader_bones_index",
                rows=10,
            )

        # Run
        row = layout.row(align=True)
        row.alignment = "LEFT"
        row.prop(
            scn, "pkl_loader_tab_run",
            text=iface_("Run"),
            emboss=False,
            icon=("TRIA_DOWN" if scn.pkl_loader_tab_run else "TRIA_RIGHT"),
        )
        if scn.pkl_loader_tab_run:
            col = layout.column(align=True)
            col.scale_y = 1.05
            col.operator("pkl_loader.apply_animation", text="Apply Animation")
            col.operator("pkl_loader.clean_animation", text="Clean Animation")
            col.separator()
            col.operator("pkl_loader.export_bvh", text="Export BVH")
            col.operator("pkl_loader.export_fbx", text="Export FBX")


# -----------------------------
# Registration
# -----------------------------
_CLASSES = [
    PKL_BoneMapItem,
    PKL_UL_BoneMap,
    PKLLOADER_OT_set_source_pkl,
    PKLLOADER_OT_apply_animation,
    PKLLOADER_OT_clean_animation,
    PKLLOADER_OT_export_bvh,
    PKLLOADER_OT_export_fbx,
    PKLLOADER_FH_PKL,
    PKLLOADER_PT_panel,
]


def register():
    # Robust translation registration for reload workflows
    try:
        bpy.app.translations.unregister(_ADDON_KEY)
    except Exception:
        pass
    try:
        bpy.app.translations.register(_ADDON_KEY, _TRANSLATIONS)
    except Exception:
        pass

    for c in _CLASSES:
        bpy.utils.register_class(c)

    bpy.types.Scene.pkl_loader_source_armature = bpy.props.PointerProperty(
        name="Source Armature",
        type=bpy.types.Object,
        poll=_armature_poll,
    )
    bpy.types.Scene.pkl_loader_source_pkl = bpy.props.StringProperty(
        name="Source PKL",
        subtype="FILE_PATH",
        default="",
    )
    bpy.types.Scene.pkl_loader_fit_timeline = bpy.props.BoolProperty(
        name="Fit to Animation Length",
        default=True,
    )
    bpy.types.Scene.pkl_loader_height = bpy.props.FloatProperty(
        name="Height",
        default=0.14,
        min=-1.0,
        max=1.0,
    )

    bpy.types.Scene.pkl_loader_tab_inputs = bpy.props.BoolProperty(default=True)
    bpy.types.Scene.pkl_loader_tab_settings = bpy.props.BoolProperty(default=True)
    bpy.types.Scene.pkl_loader_tab_run = bpy.props.BoolProperty(default=True)

    bpy.types.WindowManager.pkl_loader_bones = bpy.props.CollectionProperty(type=PKL_BoneMapItem)
    bpy.types.WindowManager.pkl_loader_bones_index = bpy.props.IntProperty(default=0)

    _schedule_populate_bones_cache()
    if _pkl_loader_on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_pkl_loader_on_load_post)


def unregister():
    try:
        if _pkl_loader_on_load_post in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_pkl_loader_on_load_post)
    except Exception:
        pass

    for prop in [
        "pkl_loader_source_armature",
        "pkl_loader_source_pkl",
        "pkl_loader_fit_timeline",
        "pkl_loader_height",
        "pkl_loader_tab_inputs",
        "pkl_loader_tab_settings",
        "pkl_loader_tab_run",
    ]:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

    for prop in ["pkl_loader_bones", "pkl_loader_bones_index"]:
        if hasattr(bpy.types.WindowManager, prop):
            delattr(bpy.types.WindowManager, prop)

    for c in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass

    try:
        bpy.app.translations.unregister(_ADDON_KEY)
    except Exception:
        pass
