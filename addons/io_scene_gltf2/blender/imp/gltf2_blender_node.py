# Copyright 2018-2021 The glTF-Blender-IO authors.
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
from mathutils import Vector, Matrix
from ...io.imp.gltf2_io_user_extensions import import_user_extensions
from ..com.gltf2_blender_extras import set_extras
from .gltf2_blender_mesh import BlenderMesh
from .gltf2_blender_camera import BlenderCamera
from .gltf2_blender_light import BlenderLight
from .gltf2_blender_vnode import VNode

class BlenderNode():
    """Blender Node."""
    def __new__(cls, *args, **kwargs):
        raise RuntimeError(f"{cls} should not be instantiated")

    @staticmethod
    def create_vnode(gltf, vnode_id):
        """Create VNode and all its descendants."""
        vnode = gltf.vnodes[vnode_id]

        gltf.display_current_node += 1
        if bpy.app.debug_value == 101:
            gltf.log.critical("Node %d of %d (id %s)", gltf.display_current_node, len(gltf.vnodes), vnode_id)

        if vnode.type == VNode.Object:
            gltf_node = gltf.data.nodes[vnode_id] if isinstance(vnode_id, int) else None
            import_user_extensions('gather_import_node_before_hook', gltf, vnode, gltf_node)
            obj = BlenderNode.create_object(gltf, vnode_id)
            import_user_extensions('gather_import_node_after_hook', gltf, vnode, gltf_node, obj)
            if vnode.is_arma:
                BlenderNode.create_bones(gltf, vnode_id)

        elif vnode.type == VNode.Bone:
            # These are created with their armature
            pass

        elif vnode.type == VNode.DummyRoot:
            # Don't actually create this
            vnode.blender_object = None

        for child in vnode.children:
            BlenderNode.create_vnode(gltf, child)

    @staticmethod
    def create_object(gltf, vnode_id):
        vnode = gltf.vnodes[vnode_id]

        if vnode.mesh_node_idx is not None:
            obj = BlenderNode.create_mesh_object(gltf, vnode)

        elif vnode.camera_node_idx is not None:
            pynode = gltf.data.nodes[vnode.camera_node_idx]
            cam = BlenderCamera.create(gltf, vnode, pynode.camera)
            name = vnode.name or cam.name
            obj = bpy.data.objects.new(name, cam)

            # Since we create the actual Blender object after the create call, we call the hook here
            import_user_extensions('gather_import_camera_after_hook', gltf, vnode, obj, cam)

        elif vnode.light_node_idx is not None:
            pynode = gltf.data.nodes[vnode.light_node_idx]
            light = BlenderLight.create(gltf, vnode, pynode.extensions['KHR_lights_punctual']['light'])
            name = vnode.name or light.name
            obj = bpy.data.objects.new(name, light)

            # Since we create the actual Blender object after the create call, we call the hook here
            import_user_extensions('gather_import_light_after_hook', gltf, vnode, obj, light)

        elif vnode.is_arma:
            armature = bpy.data.armatures.new(vnode.arma_name)
            name = vnode.name or armature.name
            obj = bpy.data.objects.new(name, armature)

        else:
            # Empty
            name = vnode.name or vnode.default_name
            obj = bpy.data.objects.new(name, None)
            obj.empty_display_size = BlenderNode.calc_empty_display_size(gltf, vnode_id)

        vnode.blender_object = obj

        # Set extras (if came from a glTF node)
        if isinstance(vnode_id, int):
            pynode = gltf.data.nodes[vnode_id]
            set_extras(obj, pynode.extras)

        # Set transform
        trans, rot, scale = vnode.trs()
        obj.location = trans
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = rot
        obj.scale = scale

        # Set parent
        if vnode.parent is not None:
            parent_vnode = gltf.vnodes[vnode.parent]
            if parent_vnode.type == VNode.Object:
                obj.parent = parent_vnode.blender_object
            elif parent_vnode.type == VNode.Bone:
                arma_vnode = gltf.vnodes[parent_vnode.bone_arma]
                obj.parent = arma_vnode.blender_object
                obj.parent_type = 'BONE'
                obj.parent_bone = parent_vnode.blender_bone_name

                # Nodes with a bone parent need to be translated
                # backwards from the tip to the root
                obj.location += Vector((0, -parent_vnode.bone_length, 0))

        # Store Rest matrix of object
        # Can't use directly matrix_world because not refreshed yet
        if hasattr(obj, 'gltf2_animation_rest'):
            obj.gltf2_animation_rest = Matrix.LocRotScale(obj.location, obj.rotation_quaternion, obj.scale)

        bpy.data.scenes[gltf.blender_scene].collection.objects.link(obj)

        return obj

    @staticmethod
    def calc_empty_display_size(gltf, vnode_id):
        # Use min distance to parent/children to guess size
        sizes = []
        vids = [vnode_id] + gltf.vnodes[vnode_id].children
        for vid in vids:
            vnode = gltf.vnodes[vid]
            dist = vnode.trs()[0].length
            sizes.append(dist * 0.4)
        return max(min(sizes, default=1), 0.001)

    @staticmethod
    def create_bones(gltf, arma_id):
        arma = gltf.vnodes[arma_id]
        blender_arma = arma.blender_object
        armature = blender_arma.data

        # Find all bones for this arma
        bone_ids = []
        def visit(id):  # Depth-first walk
            if gltf.vnodes[id].type == VNode.Bone:
                bone_ids.append(id)
                for child in gltf.vnodes[id].children:
                    visit(child)
        for child in arma.children:
            visit(child)

        # Switch into edit mode to create all edit bones

        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.window.scene = bpy.data.scenes[gltf.blender_scene]
        bpy.context.view_layer.objects.active = blender_arma
        bpy.ops.object.mode_set(mode="EDIT")

        for id in bone_ids:
            vnode = gltf.vnodes[id]
            editbone = armature.edit_bones.new(vnode.name or vnode.default_name)
            vnode.blender_bone_name = editbone.name
            editbone.use_connect = False  # TODO?

            # Give the position of the bone in armature space
            arma_mat = vnode.editbone_arma_mat
            editbone.head = arma_mat @ Vector((0, 0, 0))
            editbone.tail = arma_mat @ Vector((0, 1, 0))
            editbone.length = vnode.bone_length
            editbone.align_roll(arma_mat @ Vector((0, 0, 1)) - editbone.head)

            if isinstance(id, int):
                pynode = gltf.data.nodes[id]
                set_extras(editbone, pynode.extras)

        # Set all bone parents
        for id in bone_ids:
            vnode = gltf.vnodes[id]
            parent_vnode = gltf.vnodes[vnode.parent]
            if parent_vnode.type == VNode.Bone:
                editbone = armature.edit_bones[vnode.blender_bone_name]
                parent_editbone = armature.edit_bones[parent_vnode.blender_bone_name]
                editbone.parent = parent_editbone

        # Switch back to object mode and do pose bones
        bpy.ops.object.mode_set(mode="OBJECT")

        for id in bone_ids:
            vnode = gltf.vnodes[id]
            pose_bone = blender_arma.pose.bones[vnode.blender_bone_name]

            # BoneTRS = EditBone * PoseBone
            # Set PoseBone to make BoneTRS = vnode.trs.
            t, r, s = vnode.trs()
            et, er = vnode.editbone_trans, vnode.editbone_rot
            pose_bone.location = er.conjugated() @ (t - et)
            pose_bone.rotation_mode = 'QUATERNION'
            pose_bone.rotation_quaternion = er.conjugated() @ r
            pose_bone.scale = s

            if isinstance(id, int):
                pynode = gltf.data.nodes[id]
                set_extras(pose_bone, pynode.extras)

    @staticmethod
    def create_mesh_object(gltf, vnode):
        pynode = gltf.data.nodes[vnode.mesh_node_idx]
        if not (0 <= pynode.mesh < len(gltf.data.meshes)):
            # Avoid traceback for invalid gltf file: invalid reference to meshes array
            # So return an empty blender object)
            return bpy.data.objects.new(vnode.name or "Invalid Mesh Index", None)
        pymesh = gltf.data.meshes[pynode.mesh]

        # Key to cache the Blender mesh by.
        # Same cache key = instances of the same Blender mesh.
        cache_key = None
        if not pymesh.shapekey_names:
            cache_key = (pynode.skin,)
        elif pynode.weight_animation is False:
            cache_key = (pynode.skin, tuple(pynode.weights or []))
        else:
            cache_key = None  # don't use the cache at all

        if cache_key is not None and cache_key in pymesh.blender_name:
            mesh = bpy.data.meshes[pymesh.blender_name[cache_key]]
        else:
            gltf.log.info("Blender create Mesh node %s", pymesh.name or pynode.mesh)
            mesh = BlenderMesh.create(gltf, pynode.mesh, pynode.skin)
            if cache_key is not None:
                pymesh.blender_name[cache_key] = mesh.name

        name = vnode.name or mesh.name
        obj = bpy.data.objects.new(name, mesh)

        if pymesh.shapekey_names:
            BlenderNode.set_morph_weights(gltf, pynode, obj)

        if pynode.skin is not None:
            BlenderNode.setup_skinning(gltf, pynode, obj)

        return obj

    @staticmethod
    def set_morph_weights(gltf, pynode, obj):
        pymesh = gltf.data.meshes[pynode.mesh]
        weights = pynode.weights or pymesh.weights or []
        for i, weight in enumerate(weights):
            if pymesh.shapekey_names[i] is not None:
                kb = obj.data.shape_keys.key_blocks[pymesh.shapekey_names[i]]
                # extend range if needed
                if weight < kb.slider_min: kb.slider_min = weight
                if weight > kb.slider_max: kb.slider_max = weight
                kb.value = weight

                # Store default weight
                if hasattr(obj, 'gltf2_animation_weight_rest'):
                    w = obj.gltf2_animation_weight_rest.add()
                    w.val = weight

    @staticmethod
    def setup_skinning(gltf, pynode, obj):
        pyskin = gltf.data.skins[pynode.skin]

        # Armature/bones should have already been created.

        # Create an Armature modifier
        first_bone = gltf.vnodes[pyskin.joints[0]]
        arma = gltf.vnodes[first_bone.bone_arma]
        mod = obj.modifiers.new(name="Armature", type="ARMATURE")
        mod.object = arma.blender_object
