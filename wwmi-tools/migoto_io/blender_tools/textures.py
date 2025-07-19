import os
import bpy
import numpy
import re

from ...libs.directx.texconv import *
from ...libs.directx.dds import *
from ...addon.exceptions import ConfigError

from ..blender_interface.utility import *
from ..blender_interface.collections import *
from ..blender_interface.objects import *


###########################################
#生成 TGA 贴图
# create by momo    
###########################################
def convert_dds_to_tga(dds_path,tga_folder):
    texconv = Texconv()
    tga_path = os.path.join(tga_folder, "tga")
    texconv.convert_to_tga(dds_path, tga_path, cubemap_layout='h-cross', invert_normals=False, verbose=True)

def generate_tga_texture(cfg):
    folder_path = resolve_path(cfg.object_source_folder)
    print(f"test 0001:{folder_path}")
    REMOVEPATH = "blenderforld"
    if not folder_path.is_dir() or REMOVEPATH in folder_path.name.lower():
        raise ConfigError('object_source_folder', "Specified sources folder does not exist!")
    else:
        for filename in os.listdir(folder_path):
            if filename.lower().endswith('.dds'):
                dds_path = os.path.join(folder_path, filename)
                dds_header = DDSHeader.read_from_file(dds_path)
                if dds_header.get_format_as_str() == 'BC7_UNORM_SRGB' and not filename.lower().startswith("d-"):
                    newfilename = "D-" + filename
                    new_dds_path = os.path.join(folder_path, newfilename)
                    os.rename(dds_path, new_dds_path)
                else:
                    new_dds_path = dds_path
                convert_dds_to_tga(new_dds_path,folder_path)



###################################
# 导入贴图到 Blender 材质
# create by momo
###################################

def import_texture(context, obj, cfg, used_textures):
    if obj is None:
        raise ValueError("No object selected.")
    if obj.type != 'MESH':
        raise ValueError("Selected object is not a mesh.")
    
    folder_path = resolve_path(cfg.object_source_folder)
    #print(f"test:{folder_path}")
    REMOVEPATH = "blenderforld"
    if not folder_path.is_dir() or REMOVEPATH in folder_path.name.lower():
        raise ConfigError('object_source_folder', "Specified sources folder does not exist!")
    
    tga_folder_path = os.path.join(folder_path, "tga")
    if not os.path.isdir(tga_folder_path):
        generate_tga_texture(cfg)
    
    with OpenObject(context, obj, mode='OBJECT') as obj:
        # 如果对象没有材质，创建一个新的材质
        if not obj.data.materials:
            mat = bpy.data.materials.new(name=obj.name + '_mat')
            mat.use_nodes = True
            obj.data.materials.append(mat)
        else:
            mat = obj.data.materials[0]

        # 获取材质的节点树
        mat_nodes = mat.node_tree.nodes

        # 清除所有现有节点
        for node in mat_nodes:
            mat.node_tree.nodes.remove(node)

        # 创建一个新的贴图节点
        texture_node = mat_nodes.new(type='ShaderNodeTexImage')
        texture_path = assign_textures_to_objects(obj, tga_folder_path,used_textures)
        
        if texture_path is None:
            raise ValueError(f"No matching texture found for object {obj.name} in folder {tga_folder_path}")
        # 加载贴图文件
        # 创建贴图节点
        texture_node = mat_nodes.new(type='ShaderNodeTexImage')
        texture_node.image = bpy.data.images.load(texture_path)
        texture_node.image.colorspace_settings.name = 'Filmic sRGB'
        texture_node.location = (-400, 0)

        # 创建 Principled BSDF 节点
        principled_bsdf = mat_nodes.new(type='ShaderNodeBsdfPrincipled')
        principled_bsdf.location = (0, 0)

        # 创建输出节点
        output_node = mat_nodes.new(type='ShaderNodeOutputMaterial')
        output_node.location = (400, 0)

        # Base Color ← Texture Color
        mat.node_tree.links.new(principled_bsdf.inputs['Base Color'], texture_node.outputs['Color'])

        mat.node_tree.links.new(principled_bsdf.inputs['Emission Strength'], texture_node.outputs['Alpha'])

        # 设置 Emission 为黑色（如果存在）
        if 'Emission' in principled_bsdf.inputs:
            principled_bsdf.inputs['Emission'].default_value = (0.0, 0.0, 0.0, 1.0)
            mat.node_tree.links.new(output_node.inputs['Surface'], principled_bsdf.outputs['BSDF'])
        else:
            # 在 Blender 4.2+ 中没有 Emission，需要添加 Emission 节点并用 Add Shader 混合
            principled_bsdf.inputs['Emission Color'].default_value = (0.0, 0.0, 0.0, 1.0)
            mat.node_tree.links.new(output_node.inputs['Surface'], principled_bsdf.outputs['BSDF'])



def assign_textures_to_objects(obj, folder_path, used_textures):
    obj_name = obj.name
    obj_number = re.search(r'\d+', obj_name)
    obj_number = obj_number.group() if obj_number else None
    if obj_number is None:
        return None

    exact_match = None
    fallback_match = None
    fallback_match_count = float('inf')  # 当前最少数字数，初始为无穷大

    for filename in os.listdir(folder_path):
        if not (filename.lower().startswith("d-") and filename.lower().endswith('.tga')):
            continue
        if filename in used_textures:
            continue

        before_t = filename.split('t=')[0]
        texture_numbers = re.findall(r'\d+', before_t)

        if obj_number in texture_numbers:
            if len(texture_numbers) == 1 and texture_numbers[0] == obj_number:
                # 最佳：只包含这个编号
                exact_match = filename
                break
            else:
                # 多数字匹配，记录数字更少的那个作为备选
                if len(texture_numbers) < fallback_match_count:
                    fallback_match = filename
                    fallback_match_count = len(texture_numbers)

    if exact_match:
        used_textures.add(exact_match)
        return os.path.join(folder_path, exact_match)
    elif fallback_match:
        used_textures.add(fallback_match)
        return os.path.join(folder_path, fallback_match)

    return None

