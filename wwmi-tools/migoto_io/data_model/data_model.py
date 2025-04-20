import time
import json
import numpy
import bpy

from typing import Tuple, List, Dict, Optional

from .dxgi_format import DXGIFormat, DXGIType
from .byte_buffer import Semantic, AbstractSemantic, BufferSemantic, BufferLayout, NumpyBuffer
from .data_extractor import BlenderDataExtractor


class DataModel:
    flip_winding: bool = False
    flip_normal: bool = False
    flip_tangent: bool = False
    flip_bitangent_sign: bool = False

    data_extractor = BlenderDataExtractor()
    buffers_format: Dict[str, BufferLayout] = {}
    semantic_converters: Dict[AbstractSemantic, List[callable]] = {}
    format_converters: Dict[AbstractSemantic, List[callable]] = {}
    
    def get_data(self, 
                 context: bpy.types.Context, 
                 collection: bpy.types.Collection, 
                 obj: bpy.types.Object, 
                 mesh: bpy.types.Mesh, 
                 excluded_buffers: List[str], 
                 mirror_mesh: bool = False) -> Tuple[Dict[str, NumpyBuffer], int]:
        
        index_data, vertex_buffer = self.export_data(context, collection, mesh, excluded_buffers, mirror_mesh)
        buffers = self.build_buffers(index_data, vertex_buffer, excluded_buffers)
        return buffers, len(vertex_buffer)

    def build_buffers(self, index_data, vertex_buffer, excluded_buffers) -> Dict[str, NumpyBuffer]:
        start_time = time.time()

        result = {}
        for buffer_name, buffer_layout in self.buffers_format.items():
            buffer = None
            if buffer_name in excluded_buffers:
                continue
            for semantic in buffer_layout.semantics:
                if semantic.abstract.enum == Semantic.ShapeKey:
                    continue
                if semantic.abstract.enum == Semantic.Index:
                    data = index_data
                else:
                    data = vertex_buffer.get_field(semantic.get_name())
                if buffer is None:
                    buffer = NumpyBuffer(buffer_layout, size=len(data))
                buffer.import_semantic_data(data, semantic)
            result[buffer_name] = buffer

        print(f"Buffers build time: %fs ({len(result)} buffers)" % (time.time() - start_time))

        return result

    def export_data(self, context, collection, mesh, excluded_buffers, mirror_mesh: bool = False):
        export_layout, fetch_loop_data = self.make_export_layout(excluded_buffers)
        index_data, vertex_buffer = self.get_mesh_data(context, collection, mesh, export_layout, fetch_loop_data, mirror_mesh)
        return index_data, vertex_buffer

    def make_export_layout(self, excluded_buffers):
        fetch_loop_data = False

        if len(excluded_buffers) == 0:
            fetch_loop_data = True
        else:
            for buffer_name, buffer_layout in self.buffers_format.items():
                if buffer_name not in excluded_buffers:
                    for semantic in buffer_layout.semantics:
                        if semantic.abstract.enum in self.data_extractor.blender_loop_semantics:
                            fetch_loop_data = True
                            break

        export_layout = BufferLayout([])
        for buffer_name, buffer_layout in self.buffers_format.items():
            exclude_buffer = buffer_name in excluded_buffers
            for semantic in buffer_layout.semantics:
                if exclude_buffer and semantic.abstract.enum not in self.data_extractor.blender_loop_semantics:
                    continue
                if semantic.abstract.enum == Semantic.ShapeKey:
                    continue
                export_layout.add_element(semantic)

        return export_layout, fetch_loop_data

    def get_mesh_data(self, 
                      context: bpy.types.Context, 
                      collection: bpy.types.Collection,
                      mesh: bpy.types.Mesh, 
                      export_layout: BufferLayout, 
                      fetch_loop_data: bool, 
                      mirror_mesh: bool = False):
        
        vertex_ids_cache, cache_vertex_ids = None, False

        flip_winding = self.flip_winding if not mirror_mesh else not self.flip_winding
        flip_normal = self.flip_normal
        flip_tangent = self.flip_tangent
        flip_bitangent_sign = self.flip_bitangent_sign if not mirror_mesh else not self.flip_bitangent_sign

        if not fetch_loop_data:
            if collection != context.scene.wwmi_tools_settings.vertex_ids_cached_collection:
                # Cache contains data for different object and must be cleared
                context.scene.wwmi_tools_settings.vertex_ids_cache = ''
                fetch_loop_data = True
                cache_vertex_ids = True
            else:
                # Partial export is enabled
                if context.scene.wwmi_tools_settings.vertex_ids_cache:
                    # Valid vertex ids cache exists, lets load it
                    vertex_ids_cache = numpy.array(json.loads(context.scene.wwmi_tools_settings.vertex_ids_cache))
                else:
                    # Cache is clear, we'll have to fetch loop data once 
                    fetch_loop_data = True
                    cache_vertex_ids = True
        elif context.scene.wwmi_tools_settings.vertex_ids_cache:
            # We're going to fetch loop data, cache must be cleared
            context.scene.wwmi_tools_settings.vertex_ids_cache = ''

        # Copy default converters
        semantic_converters, format_converters = {}, {}
        semantic_converters.update(self.semantic_converters)
        format_converters.update(self.format_converters)

        # Add generic converters
        for semantic in export_layout.semantics:
            if flip_normal and semantic.abstract.enum == Semantic.Normal:
                self._insert_converter(semantic_converters, semantic.abstract, self.flip_vector)
            if flip_tangent and semantic.abstract.enum == Semantic.Tangent:
                self._insert_converter(semantic_converters, semantic.abstract, self.flip_vector)
            if flip_bitangent_sign and semantic.abstract.enum == Semantic.BitangentSign:
                self._insert_converter(semantic_converters, semantic.abstract, self.flip_vector)
            if mirror_mesh:
                if semantic.abstract.enum in [Semantic.Position, Semantic.Normal, Semantic.Tangent]:
                    self._insert_converter(semantic_converters, semantic.abstract, self.mirror_vector)

        # If vertex_ids_cache is *not* None, get_data method will skip loop data fetching
        index_buffer, vertex_buffer = self.data_extractor.get_data(
            mesh, export_layout, semantic_converters, format_converters, vertex_ids_cache, flip_winding=flip_winding)

        if cache_vertex_ids:
            # As vertex_ids_cache is None, get_data fetched loop data for us and we can cache vertex ids
            vertex_ids = vertex_buffer.get_field(AbstractSemantic(Semantic.VertexId).get_name())
            context.scene.wwmi_tools_settings.vertex_ids_cache = json.dumps(vertex_ids.tolist())
            context.scene.wwmi_tools_settings.vertex_ids_cached_collection = collection

        return index_buffer, vertex_buffer

    @staticmethod
    def flip_vector(data: numpy.ndarray) -> numpy.ndarray:
        return -data
    
    @staticmethod
    def mirror_vector(data: numpy.ndarray) -> numpy.ndarray:
        data[:, 0] *= -1
        return data

    @staticmethod
    def _insert_converter(converters, abstract_semantic: AbstractSemantic, converter: callable):
        if abstract_semantic not in converters.keys():
            converters[abstract_semantic] = []
        converters[abstract_semantic].insert(0, converter)
