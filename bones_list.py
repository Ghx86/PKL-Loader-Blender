# bones_list.py

# key: 'root', 'bone_00' ... 'bone_23'
# value: (SMPL English, PMX Japanese)
PART_MATCH_CUSTOM_LESS2 = {
    "root":    ("root",       "全ての親"),
    "bone_00": ("Pelvis",     "腰"),
    "bone_01": ("L_Hip",      "左足"),
    "bone_02": ("R_Hip",      "右足"),
    "bone_03": ("Spine1",     "上半身"),
    "bone_04": ("L_Knee",     "左ひざ"),
    "bone_05": ("R_Knee",     "右ひざ"),
    "bone_06": ("Spine2",     "上半身2"),
    "bone_07": ("L_Ankle",    "左足首"),
    "bone_08": ("R_Ankle",    "右足首"),
    "bone_09": ("Spine3",     "上半身3"),
    "bone_10": ("L_Foot",     "左つま先"),
    "bone_11": ("R_Foot",     "右つま先"),
    "bone_12": ("Neck",       "首"),
    "bone_13": ("L_Collar",   "左肩"),
    "bone_14": ("R_Collar",   "右肩"),
    "bone_15": ("Head",       "頭"),
    "bone_16": ("L_Shoulder", "左腕"),
    "bone_17": ("R_Shoulder", "右腕"),
    "bone_18": ("L_Elbow",    "左ひじ"),
    "bone_19": ("R_Elbow",    "右ひじ"),
    "bone_20": ("L_Wrist",    "左手首"),
    "bone_21": ("R_Wrist",    "右手首"),
    "bone_22": ("L_Hand",     "左指先"),
    "bone_23": ("R_Hand",     "右指先"),
}

def iter_bone_pairs():
    order = ["root"] + [f"bone_{i:02d}" for i in range(0, 24)]
    for k in order:
        if k in PART_MATCH_CUSTOM_LESS2:
            yield PART_MATCH_CUSTOM_LESS2[k]
