bl_info = {
    "name": "PKL Loader",
    "author": "派戸",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar",
    "description": "GVHMR SMPL-PKL Import",
    "category": "Animation",
}

from . import pkl_load

def register():
    pkl_load.register()

def unregister():
    pkl_load.unregister()
