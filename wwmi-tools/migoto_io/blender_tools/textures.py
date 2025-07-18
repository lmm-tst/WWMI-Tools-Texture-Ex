import os
import bpy
import numpy

from ...libs.directx.texconv import *
from ...addon.exceptions import ConfigError

from ..blender_interface.utility import *
from ..blender_interface.collections import *
from ..blender_interface.objects import *

def convert_dds_to_tga(dds_path,tga_folder):
    texconv = Texconv()
    tga_path = os.path.join(tga_folder, "tga")
    texconv.convert_to_tga(dds_path, tga_path, cubemap_layout='h-cross', invert_normals=False, verbose=True)

def generate_tga_texture(cfg):
    folder_path = resolve_path(cfg.object_source_folder)
    #print(f"test:{folder_path}")
    REMOVEPATH = r"F:\blenderforld"
    if not folder_path.is_dir() or os.path.samefile(folder_path, REMOVEPATH):
        raise ConfigError('object_source_folder', "Specified sources folder does not exist!")
    else:
        for filename in os.listdir(folder_path):
            if filename.lower().endswith('.dds'):
                dds_path = os.path.join(folder_path, filename)
                convert_dds_to_tga(dds_path,folder_path)


def import_texture(context, obj, texture_path):
    if obj is None:
        raise ValueError("No object selected.")
    if obj.type != 'MESH':
        raise ValueError("Selected object is not a mesh.")

    with OpenObject(context, obj, mode='OBJECT') as obj:
        # 如果对象没有材质，创建一个新的材质
        if not obj.data.materials:
            mat = bpy.data.materials.new(name="New_Material")
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
        texture_node.image = bpy.data.images.load(texture_path)
        texture_node.location = (-200, 0)

        # 创建一个 Principled BSDF 节点
        principled_bsdf = mat_nodes.new(type='ShaderNodeBsdfPrincipled')
        principled_bsdf.location = (0, 0)

        # 创建一个输出节点
        output_node = mat_nodes.new(type='ShaderNodeOutputMaterial')
        output_node.location = (200, 0)

        # 将贴图节点的颜色输出连接到 Principled BSDF 的 Base Color 输入
        mat.node_tree.links.new(principled_bsdf.inputs['Base Color'], texture_node.outputs['Color'])

        # 将 Principled BSDF 的输出连接到输出节点
        mat.node_tree.links.new(output_node.inputs['Surface'], principled_bsdf.outputs['BSDF'])