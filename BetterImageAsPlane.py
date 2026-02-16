bl_info = {
    "name": "Better Image as Plane",
    "author": "Hoshizora Chi",
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "Add > Image",
    "description": "Import image as plane and crop mesh to alpha boundary",
    "category": "Add Mesh",
}

import bpy
import bmesh
from bpy.props import StringProperty, IntProperty, FloatProperty
from bpy.types import Operator
from mathutils import Vector
from bpy.props import (
    StringProperty,
    IntProperty,
    FloatProperty,
    CollectionProperty
)
from bpy.types import Operator, OperatorFileListElement


# ------------------------------------------------------------
# Core Alpha Cropping Logic
# ------------------------------------------------------------

def crop_plane_to_alpha_boundary(obj, subdivisions=10, alpha_threshold=0.01):

    mat = obj.active_material
    if not mat or not mat.use_nodes:
        return

    image_node = None
    for node in mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE':
            image_node = node
            break

    if not image_node or not image_node.image:
        return

    image = image_node.image
    width, height = image.size

    if width == 0 or height == 0:
        return

    pixels = list(image.pixels)
    has_alpha = len(pixels) == width * height * 4

    def get_alpha_at_pixel(x, y):
        if x < 0 or x >= width or y < 0 or y >= height:
            return 0.0
        idx = (y * width + x) * 4 if has_alpha else (y * width + x) * 3
        return pixels[idx + 3] if has_alpha else 1.0

    def get_alpha_at_uv(u, v):
        return get_alpha_at_pixel(int(u * width), int(v * height))

    def is_face_transparent(face, uv_layer):
        uvs = [loop[uv_layer].uv for loop in face.loops]

        min_u = max(0.0, min(uv.x for uv in uvs))
        max_u = min(1.0, max(uv.x for uv in uvs))
        min_v = max(0.0, min(uv.y for uv in uvs))
        max_v = min(1.0, max(uv.y for uv in uvs))

        min_px = int(min_u * width)
        max_px = int(max_u * width)
        min_py = int(min_v * height)
        max_py = int(max_v * height)

        # Clamp pixel bounds
        min_px = max(0, min_px)
        max_px = min(width - 1, max_px)
        min_py = max(0, min_py)
        max_py = min(height - 1, max_py)

        for y in range(min_py, max_py + 1):
            for x in range(min_px, max_px + 1):
                if get_alpha_at_pixel(x, y) > alpha_threshold:
                    return False  # At least one visible pixel

        return True  # Fully transparent
    
    def find_alpha_edge_from_uv(u, v, search_radius=100):

        pixel_x = int(u * width)
        pixel_y = int(v * height)

        if get_alpha_at_pixel(pixel_x, pixel_y) > alpha_threshold:
            return u, v

        min_dist = float('inf')
        best_x, best_y = pixel_x, pixel_y

        for radius in range(1, search_radius):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):

                    if abs(dx) != radius and abs(dy) != radius:
                        continue

                    test_x = pixel_x + dx
                    test_y = pixel_y + dy

                    if get_alpha_at_pixel(test_x, test_y) > alpha_threshold:
                        dist = dx * dx + dy * dy
                        if dist < min_dist:
                            min_dist = dist
                            sign_x = (dx > 0) - (dx < 0)
                            sign_y = (dy > 0) - (dy < 0)
                            best_x = test_x - 10 * sign_x
                            best_y = test_y - 10 * sign_y

            if min_dist < float('inf'):
                break

        return best_x / width, best_y / height

    # ---- Edit Mode Work ----

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.subdivide(number_cuts=subdivisions)

    bm = bmesh.from_edit_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.active
    if not uv_layer:
        bpy.ops.object.mode_set(mode='OBJECT')
        return

    orig_width = obj.dimensions.x
    orig_height = obj.dimensions.y

    faces_to_delete = [f for f in bm.faces if is_face_transparent(f, uv_layer)]
    bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
    bmesh.update_edit_mesh(obj.data)
    
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.subdivide(number_cuts=2)
    
    faces_to_delete = [f for f in bm.faces if is_face_transparent(f, uv_layer)]
    bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
    bmesh.update_edit_mesh(obj.data)


    faces_to_delete = [f for f in bm.faces if is_face_transparent(f, uv_layer)]
    bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
    bmesh.update_edit_mesh(obj.data)

    boundary_verts = [
        v for v in bm.verts
        if any(e.is_boundary for e in v.link_edges)
    ]

    for vert in boundary_verts:
        uv = None
        for loop in vert.link_loops:
            uv = loop[uv_layer].uv.copy()
            break
        if not uv:
            continue

        new_u, new_v = find_alpha_edge_from_uv(uv.x, uv.y)

        vert.co.x = (new_u - 0.5) * orig_width
        vert.co.y = (new_v - 0.5) * orig_height
        vert.co.z = 0

        for loop in vert.link_loops:
            loop[uv_layer].uv.x = new_u
            loop[uv_layer].uv.y = new_v

    bmesh.update_edit_mesh(obj.data)
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=0.0001)
    bpy.ops.object.mode_set(mode='OBJECT')


# ------------------------------------------------------------
# Operator
# ------------------------------------------------------------

class IMAGE_OT_better_image_plane(Operator):
    bl_idname = "image.better_image_plane"
    bl_label = "Better Image as Plane"
    bl_options = {'REGISTER', 'UNDO'}

    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=OperatorFileListElement)

    subdivisions: IntProperty(default=10, min=1, max=100)
    alpha_threshold: FloatProperty(default=0.01, min=0.0, max=1.0)

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):

        if not self.files:
            self.report({'WARNING'}, "No files selected")
            return {'CANCELLED'}

        for file_elem in self.files:
            full_path = self.directory + file_elem.name

            bpy.ops.image.import_as_mesh_planes(
                files=[{"name": file_elem.name}],
                directory=self.directory
            )

            obj = context.active_object

            crop_plane_to_alpha_boundary(
                obj,
                subdivisions=self.subdivisions,
                alpha_threshold=self.alpha_threshold
            )

        return {'FINISHED'}


# ------------------------------------------------------------
# Menu Registration (Add > Image)
# ------------------------------------------------------------

def menu_func(self, context):
    self.layout.operator(
        IMAGE_OT_better_image_plane.bl_idname,
        icon='IMAGE_DATA'
    )


def register():
    bpy.utils.register_class(IMAGE_OT_better_image_plane)
    bpy.types.VIEW3D_MT_image_add.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_image_add.remove(menu_func)
    bpy.utils.unregister_class(IMAGE_OT_better_image_plane)


if __name__ == "__main__":
    register()