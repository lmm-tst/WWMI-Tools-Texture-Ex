import time
import shutil

from typing import List, Dict, Union
from dataclasses import dataclass, field

from ..migoto_io.blender_interface.utility import *
from ..migoto_io.blender_interface.collections import *
from ..migoto_io.blender_interface.objects import *
from ..migoto_io.blender_interface.mesh import *
from ..migoto_io.data_model.byte_buffer import NumpyBuffer

from ..extract_frame_data.metadata_format import read_metadata, ExtractedObject

from .object_merger import ObjectMerger, SkeletonType, MergedObject
from .metadata_collector import Version, ModInfo
from .texture_collector import Texture, get_textures
from .ini_maker import IniMaker

from ..migoto_io.data_model.data_model import DataModel
from .data_models.data_model_wwmi import DataModelWWMI

class Fatal(Exception): pass


data_models: Dict[str, DataModel] = {
    'WWMI': DataModelWWMI(),
}


class ModExporter:
    extracted_object: ExtractedObject
    merged_object: MergedObject
    buffers: Dict[str, NumpyBuffer]
    textures: List[Texture] = {}
    ini: IniMaker

    def __init__(self, context, cfg, excluded_buffers: List[str]):
        self.context = context
        self.cfg = cfg
        self.excluded_buffers = excluded_buffers

        self.object_source_folder = resolve_path(cfg.object_source_folder)
        self.mod_output_folder = resolve_path(cfg.mod_output_folder)
        self.meshes_path = self.mod_output_folder / 'Meshes'
        self.meshes_path.mkdir(parents=True, exist_ok=True)
        self.textures_path = self.mod_output_folder / 'Textures'
        self.textures_path.mkdir(parents=True, exist_ok=True)
        self.local_mod_logo_path = self.textures_path / 'Logo.dds'

    def export_mod(self):
        start_time = time.time()
        print(f"Mod export started for '{self.cfg.component_collection.name}' object")

        if self.cfg.custom_template_live_update:
            self.cfg.partial_export = False
            self.cfg.write_ini = True

        self.extracted_object = read_metadata(self.object_source_folder / 'Metadata.json')

        user_context = get_user_context(self.context)

        self.build_merged_object()
            
        self.build_data_buffers()

        if self.cfg.remove_temp_object:
            remove_mesh(self.merged_object.object.data)

        set_user_context(self.context, user_context)

        if not self.cfg.partial_export:
            self.textures = get_textures(self.object_source_folder)

            if self.cfg.write_ini:
                self.build_mod_ini()

        if self.cfg.custom_template_live_update:
            print(f"Total live ini template initialization time: %fs" % (time.time() - start_time))
            return

        self.write_files()

        print(f"Total mod export time: %fs" % (time.time() - start_time))

    def build_merged_object(self):
        start_time = time.time()
        object_merger = ObjectMerger(
            extracted_object=self.extracted_object,
            ignore_hidden_objects=self.cfg.ignore_hidden_objects,
            ignore_muted_shape_keys=self.cfg.ignore_muted_shape_keys,
            apply_modifiers=self.cfg.apply_all_modifiers,
            context=self.context,
            collection=self.cfg.component_collection,
            skeleton_type=SkeletonType.Merged if self.cfg.mod_skeleton_type == 'MERGED' else SkeletonType.PerComponent,
        )
        self.merged_object = object_merger.merged_object
        print(f"Merged object build time: %fs ({self.merged_object.vertex_count} vertices, {self.merged_object.index_count} indices)" % (time.time() - start_time))

    def build_data_buffers(self):
        start_time = time.time()

        global data_models
        data_model = data_models['WWMI']

        self.buffers, vertex_count = data_model.get_data(
            self.context, 
            self.cfg.component_collection, 
            self.merged_object.object, 
            self.merged_object.mesh, 
            self.excluded_buffers,
            self.cfg.mirror_mesh)

        self.merged_object.vertex_count = vertex_count
        self.merged_object.shapekeys.vertex_count = len(self.buffers.get('ShapeKeyVertexId', []))

        print(f"Total mesh data collection time: %fs" % (time.time() - start_time))

    def build_mod_ini(self):
        start_time = time.time()

        ini_maker = IniMaker(
            cfg=self.cfg,
            mod_info=ModInfo(
                wwmi_tools_version=Version(self.cfg.wwmi_tools_version),
                required_wwmi_version=Version(self.cfg.required_wwmi_version),
                mod_name=self.cfg.mod_name,
                mod_author=self.cfg.mod_author,
                mod_desc=self.cfg.mod_desc,
                mod_link=self.cfg.mod_link,
                mod_logo=self.local_mod_logo_path,
            ),
            extracted_object=self.extracted_object,
            merged_object=self.merged_object,
            buffers=self.buffers,
            textures=self.textures,
            comment_code=self.cfg.comment_ini,
            skeleton_scale=self.cfg.skeleton_scale,
            unrestricted_custom_shape_keys=self.cfg.unrestricted_custom_shape_keys,
        )

        self.ini = ini_maker

        if self.cfg.custom_template_live_update:
            self.ini.start_live_write(self.context, self.cfg)
        else:
            self.ini.build_from_template(self.context, self.cfg, with_checksum=True)

        print(f"Total mod ini build time: %fs" % (time.time() - start_time))

    def write_files(self):
        start_time = time.time()

        for buffer_name, buffer in self.buffers.items():
            print(f'Writing {buffer_name}.buf...')
            with open(self.meshes_path / f'{buffer_name}.buf', 'wb') as f:
                f.write(buffer.get_bytes())

        if not self.cfg.partial_export:
                
            if self.cfg.copy_textures:
                missing_textures = []
                for texture in self.textures:
                    texture_path = self.textures_path / texture.filename
                    if texture_path.is_file():
                        continue
                    missing_textures.append[texture_path]
                if len(missing_textures) > 0:
                    for texture_path in missing_textures:
                        print(f'Copying {texture_path.name}...')
                        shutil.copy(texture.path, texture_path)

            mod_logo_path = resolve_path(self.cfg.mod_logo)
            if mod_logo_path.is_file():
                print(f'Copying {self.local_mod_logo_path.name}...')
                shutil.copy(mod_logo_path, self.local_mod_logo_path)

            if self.cfg.write_ini:
                self.ini.write(ini_path=self.mod_output_folder / 'mod.ini')
                # self.ini.write(ini_path=self.mod_output_folder / 'mod_old.ini', ini_string=self.ini.build_old())
                
        print(f"Disk write time: %fs" % (time.time() - start_time))


def blender_export(operator, context, cfg, excluded_buffers):
    mod_exporter = ModExporter(context, cfg, excluded_buffers)
    mod_exporter.export_mod()
