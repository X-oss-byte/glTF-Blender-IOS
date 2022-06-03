# Copyright 2018-2022 The glTF-Blender-IO authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import bpy
from io_scene_gltf2.io.com.gltf2_io_extensions import Extension
from io_scene_gltf2.blender.exp import gltf2_blender_get
from io_scene_gltf2.io.com.gltf2_io_constants import GLTF_IOR
from io_scene_gltf2.blender.com.gltf2_blender_default import BLENDER_SPECULAR, BLENDER_SPECULAR_TINT
from io_scene_gltf2.blender.exp import gltf2_blender_gather_texture_info

def export_specular(blender_material, export_settings):
    specular_extension = {}
    specular_ext_enabled = False

    specular_socket = gltf2_blender_get.get_socket(blender_material, 'Specular')
    specular_tint_socket = gltf2_blender_get.get_socket(blender_material, 'Specular Tint')
    base_color_socket = gltf2_blender_get.get_socket(blender_material, 'Base Color')
    transmission_socket = gltf2_blender_get.get_socket(blender_material, 'Transmission')
    ior_socket = gltf2_blender_get.get_socket(blender_material, 'IOR')

    if base_color_socket is None:
        return None, None

    # TODOExt replace by __has_image_node_from_socket calls
    specular_not_linked = isinstance(specular_socket, bpy.types.NodeSocket) and not specular_socket.is_linked
    specular_tint_not_linked = isinstance(specular_tint_socket, bpy.types.NodeSocket) and not specular_tint_socket.is_linked
    base_color_not_linked = isinstance(base_color_socket, bpy.types.NodeSocket) and not base_color_socket.is_linked
    transmission_not_linked = isinstance(transmission_socket, bpy.types.NodeSocket) and not transmission_socket.is_linked
    ior_not_linked = isinstance(ior_socket, bpy.types.NodeSocket) and not ior_socket.is_linked

    specular = specular_socket.default_value if specular_not_linked else None
    specular_tint = specular_tint_socket.default_value if specular_tint_not_linked else None
    transmission = transmission_socket.default_value if transmission_not_linked else None
    ior = ior_socket.default_value if ior_not_linked else GLTF_IOR   # textures not supported #TODOExt add warning?
    base_color = base_color_socket.default_value[0:3]

    no_texture = (transmission_not_linked and specular_not_linked and specular_tint_not_linked and
        (specular_tint == 0.0 or (specular_tint != 0.0 and base_color_not_linked)))

    use_actives_uvmaps = []

    if no_texture:
        import numpy as np
        # See https://gist.github.com/proog128/d627c692a6bbe584d66789a5a6437a33
        specular_ext_enabled = True

        def normalize(c):
            luminance = lambda c: 0.3 * c[0] + 0.6 * c[1] + 0.1 * c[2]
            assert(len(c) == 3)
            l = luminance(c)
            if l == 0:
                return c
            return np.array([c[0] / l, c[1] / l, c[2] / l])            

        f0_from_ior = ((ior - 1)/(ior + 1))**2
        tint_strength = (1 - specular_tint) + normalize(base_color) * specular_tint
        specular_color = (1 - transmission) * (1 / f0_from_ior) * 0.08 * specular * tint_strength + transmission * tint_strength
        specular_extension['specularColorFactor'] = list(specular_color)
    else:
        # There will be a texture, with a complex calculation (no direct channel mapping)
        sockets = (specular_socket, specular_tint_socket, base_color_socket, transmission_socket, ior_socket)
        # Set primary socket having a texture
        primary_socket = specular_socket
        if specular_not_linked:
            primary_socket = specular_tint_socket
            if specular_tint_not_linked:
                primary_socket = base_color_socket
                if base_color_not_linked:
                    primary_socket = transmission_socket

        specularColorTexture, use_active_uvmap, specularColorFactor = gltf2_blender_gather_texture_info.gather_texture_info(
            primary_socket, 
            sockets, 
            export_settings,
            filter_type='ANY')
        if specularColorTexture is None:
            return None, None
        if use_active_uvmap:
            use_actives_uvmaps.append("specularColorTexture")

        specular_ext_enabled = True
        specular_extension['specularColorTexture'] = specularColorTexture


        if specularColorFactor is not None:
            specular_extension['specularColorFactor'] = specularColorFactor
            

    specular_extension = Extension('KHR_materials_specular', specular_extension, False) if specular_ext_enabled else None
    return specular_extension, use_actives_uvmaps