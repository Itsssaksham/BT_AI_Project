# import json
# from typing import Any, Dict, List

# import ezdxf
# import numpy as np
# from scipy.spatial import ConvexHull
# from fastapi import HTTPException

# from call_gemini import call_llm

# async def extract_steelwork_boundary(file_path: str, layer_name: str = "STEELWORK") -> List[List[float]]:
#     """
#     Parses the DXF file, filters out entities belonging to the specified layer,
#     and returns the outer boundary (convex hull) vertices representing the rail.
#     """
#     try:
#         doc = ezdxf.readfile(file_path)
#     except IOError:
#         raise HTTPException(status_code=400, detail="Not a valid DXF file or file missing.")
#     except ezdxf.DXFStructureError:
#         raise HTTPException(status_code=400, detail="Invalid or corrupted DXF structure.")

#     msp = doc.modelspace()
#     points = []

#     # Query lines, polylines, and lwpolylines belonging to the target layer
#     query_str = f'*[layer=="{layer_name}"]'
#     for entity in msp.query(query_str):
#         dxftype = entity.dxftype()
        
#         if dxftype == 'LINE':
#             points.append([entity.dxf.start.x, entity.dxf.start.y])
#             points.append([entity.dxf.end.x, entity.dxf.end.y])
            
#         elif dxftype == 'LWPOLYLINE':
#             # LWPOLYLINE vertices are returned as tuples: (x, y, [start_width, end_width, bulge])
#             for vertex in entity.vertices():
#                 points.append([vertex[0], vertex[1]])
                
#         elif dxftype == 'POLYLINE':
#             # Old-style POLYLINE vertices are DXF objects with .x, .y attributes
#             for vertex in entity.vertices():
#                 points.append([vertex.dxf.location.x, vertex.dxf.location.y])

#     if not points:
#         raise HTTPException(
#             status_code=404, 
#             detail=f"No geometry found on layer '{layer_name}'. Please verify your layer name casing."
#         )

#     # Convert to a unique numpy array of 2D points, dropping any Z coordinates
#     unique_points = np.unique(np.array(points)[:, :2], axis=0)

#     if len(unique_points) < 3:
#         # Not enough points to form a polygon, return raw coordinate array
#         return unique_points.tolist()

#     # Use Convex Hull to isolate the outermost points (the boundary rail framework)
#     hull = ConvexHull(unique_points)
#     boundary_vertices = unique_points[hull.vertices].tolist()

#     return boundary_vertices


# async def analyze_structure_with_llm(vertices: List[List[float]]) -> Dict[str, Any]:
#     """
#     Sends the outer boundary coordinates to Gemini to classify the structure.
#     The dynamic schema lets the LLM decide node mapping based on structural type.
#     """
    
#     # Provide an explicit example to the LLM within the prompt text
#     prompt = """
#     You are a structural engineering assistant analyzing telecommunication tower mounts.
#     I have filtered out a CAD drawing's 'STEELWORK' layer and extracted the outermost bounding rail coordinates (vertices).
    
    
    
#     Your Task:
#     1. Identify the geometric structure type (e.g., 'triangular', 'square', 'pentagonal', 'circular', 'monopole').
#     2. Provide all the sorted outer boundary vertices.
#     3. Label and map the key spatial nodes dynamically according to the structure. For example, if it's triangular, label them 'TL' (Top Left), 'TR' (Top Right), 'BOT' (Bottom). If it's square, use 'TL', 'TR', 'BL', 'BR'. If it's a circle/monopole, map the appropriate cardinal direction points or core anchor nodes.
    
#     Example format if a structure is found to be triangular (use this exact JSON key architecture but adapt the content dynamically):
#     {
#       "headframe": {
#         "type": "triangular",
#         "vertices": [
#           [180, 148],
#           [487, 148],
#           [334, 430]
#         ],
#         "nodes": {
#           "TL":  [180, 148],
#           "TR":  [487, 148],
#           "BOT": [334, 430]
#         }
#       }
#     }
    
#     Return ONLY valid raw JSON matching this architecture. Do not include markdown wraps or conversational text.
#     """

#     f_prompt = f"""
#         {prompt}

#         Extracted Coordinates:
#         {vertices}

#      """

#     try:
#         response = await call_llm(f_prompt)

#         return response
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"AI Processing failed: {str(e)}")







# import ezdxf
# import numpy as np
# from scipy.spatial import cKDTree
# from collections import deque

# def extract_entity_vertices(entity):
#     """Extracts all significant coordinate points from a DXF entity."""
#     points = []
#     dxftype = entity.dxftype()
    
#     if dxftype == 'LINE':
#         points.append((entity.dxf.start.x, entity.dxf.start.y))
#         points.append((entity.dxf.end.x, entity.dxf.end.y))
        
#     elif dxftype in ('LWPOLYLINE', 'POLYLINE'):
#         for vertex in entity.get_points():
#             points.append((vertex[0], vertex[1]))
            
#     elif dxftype in ('CIRCLE', 'ARC'):
#         cx, cy = entity.dxf.center.x, entity.dxf.center.y
#         r = entity.dxf.radius
#         # Include center and cardinal points so arcs/circles link to surrounding lines
#         points.append((cx, cy))
#         points.append((cx + r, cy))
#         points.append((cx - r, cy))
#         points.append((cx, cy + r))
#         points.append((cx, cy - r))
        
#     return points

# async def group_by_vertex_chain(dxf_path, layer_name="ANTENNAS DISHES", max_link_distance=100.0):
#     try:
#         doc = ezdxf.readfile(dxf_path)
#     except IOError:
#         raise HTTPException(status_code=400, detail="Cannot open or find the DXF file.")
#     except ezdxf.DXFStructureError:
#         raise HTTPException(status_code=400, detail="Invalid or corrupted DXF structure.")
        
#     msp = doc.modelspace()
#     layer_entities = list(msp.query(f'*[layer=="{layer_name}"]'))
    
#     if not layer_entities:
#         return {"status": "success", "message": f"No entities found on layer '{layer_name}'", "antenna_clusters": {}}
        
#     # 1. Map every vertex back to its parent entity index
#     all_points = []
#     point_to_entity_idx = []
    
#     for ent_idx, entity in enumerate(layer_entities):
#         vertices = extract_entity_vertices(entity)
#         for pt in vertices:
#             all_points.append(pt)
#             point_to_entity_idx.append(ent_idx)
            
#     if not all_points:
#         raise HTTPException(status_code=422, detail="No processable geometric vertices found on this layer.")
        
#     X = np.array(all_points)
#     point_to_entity_idx = np.array(point_to_entity_idx)
    
#     # 2. Build a KDTree for fast spatial proximity lookups
#     tree = cKDTree(X)
    
#     # 3. Build an Adjacency List for the entities
#     num_entities = len(layer_entities)
#     adjacency_list = {i: set() for i in range(num_entities)}
    
#     # Query all pairs within max_link_distance threshold
#     pairs = tree.query_pairs(r=max_link_distance)
#     for p1, p2 in pairs:
#         ent1 = point_to_entity_idx[p1]
#         ent2 = point_to_entity_idx[p2]
#         if ent1 != ent2:
#             adjacency_list[ent1].add(ent2)
#             adjacency_list[ent2].add(ent1)
            
#     # 4. Chain tracking using BFS (Breadth-First Search)
#     visited = [False] * num_entities
#     serializable_clusters = {}
#     group_counter = 0
    
#     for ent_idx in range(num_entities):
#         if visited[ent_idx]:
#             continue
            
#         queue = deque([ent_idx])
#         visited[ent_idx] = True
        
#         cluster_elements = []
        
#         while queue:
#             curr = queue.popleft()
#             entity = layer_entities[curr]
            
#             # --- FIX FOR FASTAPI: Convert the ezdxf object data into primitive types ---
#             entity_data = {
#                 "handle": str(entity.dxf.handle),  # Unique CAD handle string
#                 "type": str(entity.dxftype()),     # LINE, LWPOLYLINE, ARC, etc.
#             }
#             cluster_elements.append(entity_data)
            
#             # Traversal loop to find neighboring linked entities
#             for neighbor in adjacency_list[curr]:
#                 if not visited[neighbor]:
#                     visited[neighbor] = True
#                     queue.append(neighbor)
                    
#         # Group ID keys must be strings for JSON standard compliance
#         serializable_clusters[f"antenna_{group_counter}"] = cluster_elements
#         group_counter += 1

#     # 5. Safely return the dictionary. FastAPI handles the serialization effortlessly now!
#     return {
#         "status": "success", 
#         "total_antennas_found": len(serializable_clusters),
#         "antenna_clusters": serializable_clusters
#     }

# async def auto_analyze_drawing(file: str, img: str):
    
#     analysis_result = await group_by_vertex_chain(file)

#     return analysis_result



# import ezdxf
# import numpy as np
# from scipy.spatial import cKDTree
# from collections import deque
# from fastapi import HTTPException

# def extract_entity_vertices(entity):
#     """Extracts all significant coordinate points from a DXF entity."""
#     points = []
#     dxftype = entity.dxftype()
    
#     if dxftype == 'LINE':
#         points.append((entity.dxf.start.x, entity.dxf.start.y))
#         points.append((entity.dxf.end.x, entity.dxf.end.y))
        
#     elif dxftype in ('LWPOLYLINE', 'POLYLINE'):
#         for vertex in entity.get_points():
#             points.append((vertex[0], vertex[1]))
            
#     elif dxftype in ('CIRCLE', 'ARC'):
#         cx, cy = entity.dxf.center.x, entity.dxf.center.y
#         r = entity.dxf.radius
#         # Include center and cardinal points so arcs/circles link to surrounding lines
#         points.append((cx, cy))
#         points.append((cx + r, cy))
#         points.append((cx - r, cy))
#         points.append((cx, cy + r))
#         points.append((cx, cy - r))
        
#     return points

# async def group_by_vertex_chain(dxf_path, layer_name="ANTENNAS DISHES", max_link_distance=100.0):
#     try:
#         doc = ezdxf.readfile(dxf_path)
#     except IOError:
#         raise HTTPException(status_code=400, detail="Cannot open or find the DXF file.")
#     except ezdxf.DXFStructureError:
#         raise HTTPException(status_code=400, detail="Invalid or corrupted DXF structure.")
        
#     msp = doc.modelspace()
#     layer_entities = list(msp.query(f'*[layer=="{layer_name}"]'))
    
#     if not layer_entities:
#         return {"status": "success", "message": f"No entities found on layer '{layer_name}'", "antenna_clusters": {}}
        
#     # 1. Map every vertex back to its parent entity index
#     all_points = []
#     point_to_entity_idx = []
    
#     for ent_idx, entity in enumerate(layer_entities):
#         vertices = extract_entity_vertices(entity)
#         for pt in vertices:
#             all_points.append(pt)
#             point_to_entity_idx.append(ent_idx)
            
#     if not all_points:
#         raise HTTPException(status_code=422, detail="No processable geometric vertices found on this layer.")
        
#     X = np.array(all_points)
#     point_to_entity_idx = np.array(point_to_entity_idx)
    
#     # 2. Build a KDTree for fast spatial proximity lookups
#     tree = cKDTree(X)
    
#     # 3. Build an Adjacency List for the entities
#     num_entities = len(layer_entities)
#     adjacency_list = {i: set() for i in range(num_entities)}
    
#     # Query all pairs within max_link_distance threshold
#     pairs = tree.query_pairs(r=max_link_distance)
#     for p1, p2 in pairs:
#         ent1 = point_to_entity_idx[p1]
#         ent2 = point_to_entity_idx[p2]
#         if ent1 != ent2:
#             adjacency_list[ent1].add(ent2)
#             adjacency_list[ent2].add(ent1)
            
#     # 4. Chain tracking using BFS (Breadth-First Search)
#     visited = [False] * num_entities
#     serializable_clusters = {}
#     group_counter = 0
    
#     for ent_idx in range(num_entities):
#         if visited[ent_idx]:
#             continue
            
#         queue = deque([ent_idx])
#         visited[ent_idx] = True
        
#         cluster_elements = []
        
#         while queue:
#             curr = queue.popleft()
#             entity = layer_entities[curr]
            
#             # --- UPDATED: Extract raw coordinates for serialization ---
#             raw_coordinates = extract_entity_vertices(entity)
            
#             entity_data = {
#                 "handle": str(entity.dxf.handle),  # Unique CAD handle string
#                 "type": str(entity.dxftype()),     # LINE, LWPOLYLINE, ARC, etc.
#                 "coordinates": raw_coordinates      # List of (x, y) tuples 
#             }
#             cluster_elements.append(entity_data)
            
#             # Traversal loop to find neighboring linked entities
#             for neighbor in adjacency_list[curr]:
#                 if not visited[neighbor]:
#                     visited[neighbor] = True
#                     queue.append(neighbor)
                    
#         # Group ID keys must be strings for JSON standard compliance
#         serializable_clusters[f"antenna_{group_counter}"] = cluster_elements
#         group_counter += 1

#     # 5. Safely return the dictionary. FastAPI handles the serialization effortlessly now!
#     return {
#         "status": "success", 
#         "total_antennas_found": len(serializable_clusters),
#         "antenna_clusters": serializable_clusters
#     }

# async def auto_analyze_drawing(file: str, img: str):
#     analysis_result = await group_by_vertex_chain(file)
#     return analysis_result


from PIL import Image
import fitz
import io
import os
import re
import json
import ezdxf
import numpy as np
from scipy.spatial import cKDTree
from collections import deque
from fastapi import HTTPException
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing import pymupdf
from ezdxf.math import BoundingBox
import math

from call_gemini import call_llm

def extract_entity_vertices(entity):
    """Extracts all significant coordinate points from a DXF entity."""
    points = []
    dxftype = entity.dxftype()
    
    if dxftype == 'LINE':
        points.append((entity.dxf.start.x, entity.dxf.start.y))
        points.append((entity.dxf.end.x, entity.dxf.end.y))
        
    elif dxftype in ('LWPOLYLINE', 'POLYLINE'):
        for vertex in entity.get_points():
            points.append((vertex[0], vertex[1]))
            
    elif dxftype in ('CIRCLE', 'ARC'):
        cx, cy = entity.dxf.center.x, entity.dxf.center.y
        r = entity.dxf.radius
        points.append((cx, cy))
        points.append((cx + r, cy))
        points.append((cx - r, cy))
        points.append((cx, cy + r))
        points.append((cx, cy - r))
        
    return points

async def group_by_vertex_chain(dxf_path, layer_name="ANTENNAS DISHES", max_link_distance=100.0):
    try:
        doc = ezdxf.readfile(dxf_path)
    except IOError:
        raise HTTPException(status_code=400, detail="Cannot open or find the DXF file.")
    except ezdxf.DXFStructureError:
        raise HTTPException(status_code=400, detail="Invalid or corrupted DXF structure.")
        
    msp = doc.modelspace()
    layer_entities = list(msp.query(f'*[layer=="{layer_name}"]'))
    
    if not layer_entities:
        return {"status": "success", "message": f"No entities found on layer '{layer_name}'", "clusters": []}
        
    all_points = []
    point_to_entity_idx = []
    
    for ent_idx, entity in enumerate(layer_entities):
        vertices = extract_entity_vertices(entity)
        for pt in vertices:
            all_points.append(pt)
            point_to_entity_idx.append(ent_idx)
            
    if not all_points:
        raise HTTPException(status_code=422, detail="No processable geometric vertices found on this layer.")
        
    X = np.array(all_points)
    point_to_entity_idx = np.array(point_to_entity_idx)
    
    tree = cKDTree(X)
    num_entities = len(layer_entities)
    adjacency_list = {i: set() for i in range(num_entities)}
    
    pairs = tree.query_pairs(r=max_link_distance)
    for p1, p2 in pairs:
        ent1 = point_to_entity_idx[p1]
        ent2 = point_to_entity_idx[p2]
        if ent1 != ent2:
            adjacency_list[ent1].add(ent2)
            adjacency_list[ent2].add(ent1)
            
    visited = [False] * num_entities
    clusters = []
    
    for ent_idx in range(num_entities):
        if visited[ent_idx]:
            continue
            
        queue = deque([ent_idx])
        visited[ent_idx] = True
        cluster_entities = []
        
        while queue:
            curr = queue.popleft()
            entity = layer_entities[curr]
            cluster_entities.append(entity)
            
            for neighbor in adjacency_list[curr]:
                if not visited[neighbor]:
                    visited[neighbor] = True
                    queue.append(neighbor)
                    
        clusters.append(cluster_entities)

    return {"doc": doc, "clusters": clusters}


# async def label_dxf_clusters(file_path: str, output_suffix: str = "_labeled", text_height: float = 125.0, offset_distance: float = 20.0) -> str:
#     """
#     Reads the DXF file, groups components, overlays 'antenna_X' labels 
#     outside their bounding box to avoid collision, and saves a new copy.
#     """
    
#     if not os.path.exists(file_path):
#         raise HTTPException(status_code=404, detail="Source DXF file not found.")

#     # 1. Reuse vertex chain logic to isolate cluster objects natively
#     data = await group_by_vertex_chain(file_path)
#     doc = data["doc"]
#     clusters = data["clusters"]
    
#     msp = doc.modelspace()
    
#     # Ensure a dedicated text layer exists for styling control
#     label_layer = "ANTENNA_LABELS"
#     if label_layer not in doc.layers:
#         doc.layers.new(name=label_layer, dxfattribs={'color': 2}) # Yellow color for visibility

#     for idx, cluster in enumerate(clusters):
#         cluster_points = []
#         for entity in cluster:
#             cluster_points.extend(extract_entity_vertices(entity))
            
#         if not cluster_points:
#             continue
            
#         # 2. Compute spatial Bounding Box for non-intersecting placement
#         arr = np.array(cluster_points)
#         min_x, min_y = np.min(arr, axis=0)
#         max_x, max_y = np.max(arr, axis=0)
        
#         # 3. Position text safely above the highest Y-bound with a buffer offset
#         # This keeps the label completely out of the interior geometry zone
#         label_x = min_x
#         label_y = max_y + offset_distance
        
#         label_text = f"antenna_{idx}"
        
#         # 4. Burn label entity directly into CAD Modelspace
#         msp.add_text(
#             text=label_text,
#             dxfattribs={
#                 'layer': label_layer,
#                 'height': text_height,
#                 'insert': (label_x, label_y)
#             }
#         )

#     # 5. Generate unique name variant and persist file structural updates
#     base, ext = os.path.splitext(file_path)
#     output_path = f"{base}{output_suffix}{ext}"
#     doc.saveas(output_path)
    
#     return output_path

async def label_dxf_clusters(
    file_path: str, 
    output_suffix: str = "_labeled", 
    text_height: float = 125.0, 
    offset_distance: float = 20.0
) -> dict:
    """
    Reads the DXF file, groups components, overlays 'antenna_X' labels,
    saves the modified CAD file, and returns serializable cluster metadata.
    """
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Source DXF file not found.")

    # 1. Reuse vertex chain logic to isolate cluster objects natively
    data = await group_by_vertex_chain(file_path)
    doc = data["doc"]
    clusters = data["clusters"]
    
    msp = doc.modelspace()
    
    # Ensure a dedicated text layer exists for styling control
    label_layer = "ANTENNA_LABELS"
    if label_layer not in doc.layers:
        doc.layers.new(name=label_layer, dxfattribs={'color': 2}) # Yellow color for visibility

    # Prepare our structured dictionary for the final JSON output
    serialized_clusters = {}

    for idx, cluster in enumerate(clusters):
        cluster_points = []
        entities_metadata = []
        
        for entity in cluster:
            raw_vertices = extract_entity_vertices(entity)
            cluster_points.extend(raw_vertices)
            
            # Serialize individual entity details for backend calculations
            entities_metadata.append({
                "id": str(entity.dxf.handle),       # Unique CAD handle id
                "type": str(entity.dxftype()),       # LINE, LWPOLYLINE, ARC, etc.
                "vertices": raw_vertices             # List of extracted (x, y) tuples
            })
            
        if not cluster_points:
            continue
            
        # 2. Compute spatial Bounding Box for non-intersecting placement
        arr = np.array(cluster_points)
        min_x, min_y = np.min(arr, axis=0)
        max_x, max_y = np.max(arr, axis=0)
        
        # 3. Position text safely above the highest Y-bound with a buffer offset
        label_x = min_x
        label_y = max_y + offset_distance
        
        cluster_key = f"antenna_{idx}"
        
        # 4. Burn label entity directly into CAD Modelspace
        msp.add_text(
            text=cluster_key,
            dxfattribs={
                'layer': label_layer,
                'height': text_height,
                'insert': (label_x, label_y)
            }
        )
        
        # 5. Cache calculation-heavy metadata (like center of mass) for radiation modeling
        center_x, center_y = np.mean(arr, axis=0)
        
        serialized_clusters[cluster_key] = {
            "center": [float(center_x), float(center_y)],
            "bounding_box": {
                "min_x": float(min_x), "min_y": float(min_y),
                "max_x": float(max_x), "max_y": float(max_y)
            },
            "entities": entities_metadata
        }

    # 6. Generate unique name variant and persist file structural updates
    base, ext = os.path.splitext(file_path)
    output_path = f"{base}{output_suffix}{ext}"
    doc.saveas(output_path)
    
    # Return everything cleanly packed for FastAPI serialization
    return {
        "status": "success",
        "output_path": output_path,
        "clusters": serialized_clusters
    }

Image.MAX_IMAGE_PIXELS = None
async def label_and_snapshot_dxf(
    dxf_path: str, 
    output_img_name: str = "dxf_snap", 
    max_edge_pixels: int = 2048  # Sets a strict upper bound on the image resolution
):
    if not os.path.exists(dxf_path):
        raise HTTPException(status_code=404, detail="Target DXF file not found.")
        
    try:
        # 1. Read the already labeled DXF document
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        
        # 2. Extract vertices from the targeted geometry layer to determine bounds
        layer_name = "ANTENNAS DISHES"
        layer_entities = list(msp.query(f'*[layer=="{layer_name}"]'))
        if not layer_entities:
            layer_entities = list(msp)
            
        if not layer_entities:
            raise HTTPException(status_code=422, detail="No visible geometry found to render.")
            
        all_scene_points = []
        for entity in layer_entities:
            entity_pts = extract_entity_vertices(entity)
            if entity_pts:
                all_scene_points.extend(entity_pts)
                
        # 3. Calculate bounding box dimensions based purely on geometry bounds
        scene_arr = np.array(all_scene_points)
        s_min_x, s_min_y = np.min(scene_arr, axis=0)
        s_max_x, s_max_y = np.max(scene_arr, axis=0)
        
        margin_y = 400.0  
        margin_x = 800.0  

        width = (s_max_x - s_min_x) + (margin_x * 2)
        height = (s_max_y - s_min_y) + (margin_y * 2)
        
        render_box = BoundingBox([
            (s_min_x - margin_x, s_min_y - margin_y), 
            (s_max_x + margin_x, s_max_y + margin_y)
        ])
        
        # 4. Dynamic DPI Calculation to prevent decompression-bomb errors
        max_drawing_units = max(width, height)
        calculated_dpi = int((max_edge_pixels / max_drawing_units) * 72)
        
        # Clamp DPI bounds to keep it sharp but performant
        calculated_dpi = max(min(calculated_dpi, 300), 45)
        
        # 5. Wire the PyMuPDF rendering pipeline
        ctx = RenderContext(doc)
        backend = pymupdf.PyMuPdfBackend()
        Frontend(ctx, backend).draw_layout(msp)
        
        # Render the cropped view using our pre-calculated BoundingBox
        ppm_bytes = backend.get_pixmap_bytes(
            page=layout.Page(0, 0),
            fmt="ppm",
            dpi=calculated_dpi,
            render_box=render_box
        )

        dxf_filename = os.path.basename(dxf_path)  
        dxf_name = os.path.splitext(dxf_filename)[0]
        output_path = f"{output_img_name}/{dxf_name}.png"
        
        # 6. Save directly to PNG using Pillow
        with io.BytesIO(ppm_bytes) as stream:
            with Image.open(stream, formats=["ppm"]) as img:
                img.save(output_path, format="PNG")
                
        return {
            "status": "success",
            "saved_snapshot": output_path,
            "rendered_dpi": calculated_dpi
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate snapshot: {str(e)}")

async def get_antenna(img_path: str, snapshot_path: str, input_params: str):

    try:

        prompt = f"""
            # Role & Objective
You are an expert Telecom Spatial Analysis AI. Your task is to cross-reference text specifications, a metadata-labeled sketch (Image B), and an indexed equipment sketch (Image A) to precisely identify specific antennas on a telecom headframe while filtering out non-antenna equipment and duplicate artifacts.

# Input Data Provided
1. **Image A (Indexed Sketch):** A top-view headframe sketch where *all* detected equipment is heavily indexed with labels like `antenna_0`, `antenna_1`, `antenna_2`, etc. Note: Despite the "antenna_" naming convention, these labels apply to all physical equipment (antennas, microwave dishes, RRUs, mounts, etc.).
2. **Image B (Metadata Sketch):** The exact same top-view headframe sketch, but labeled with engineering metadata such as Antenna Names (e.g., "742215V01"), Heights, and Azimuths.
3. **Target Antenna Text Details:** A text snippet detailing the specific antenna you need to locate (e.g., Model, Height, Sector, Azimuth).

---

# Execution Pipeline (Chain-of-Thought)

You must process the inputs step-by-step using the following strict logic pipeline:

### Step 1: Parse the Target Text
Identify the core physical attributes of the target antenna from the provided text details (e.g., Azimuth angle, Model Name, and Center Line / Height).

### Step 2: Locate on Image B (Metadata Sketch)
* Scan **Image B** to find the equipment cluster or position that matches the Target Text attributes (matching the correct sector azimuth and height/model tags). 
* Pinpoint its exact spatial location on the headframe structure.

### Step 3: Map to Image A (Indexed Sketch) & Filter Equipment
* Look at the exact same spatial location on **Image A** to find the corresponding `antenna_X` label.
* **Strict Filter Rule:** You must *only* target actual antennas. If the mapped location on Image A points to a microwave dish, an RRU (typically mounted directly behind or on the bottom rail of an antenna), or an empty pole mount, **do not select it**. Keep searching Image B for the true antenna matching the specifications.

### Step 4: Validate Against Duplicates
* Inspect Image A to check if the same physical piece of equipment has been mistakenly cross-labeled with two different index tags (e.g., both `antenna_3` and `antenna_4` pointing to the exact same physical chassis).
* **If a duplicate labeling error is detected on the target equipment:** Abort the automated match for this specific target, skip to the fallback output, and do not attempt a random guess.

---

# Output Protocol & Guardrails

Your final response must follow one of these two strict criteria:

### Scenario 1: Successful Match
If you successfully locate the unique true antenna, verify it isn't an RRU/dish, and find no duplicate label bugs, output **only** the following JSON block:
```json
{{
  "status": "Success",
  "matched_index": "antenna_X", 
  "reasoning": "Briefly state the matched azimuth/height from Image B and verify it is a valid antenna on Image A."
}}
```
Input params:
{input_params}
        
         """

        response = await call_llm(prompt, [img_path, snapshot_path])

        # 2. Extract the nested text string from the Gemini API response structure
        # Depending on whether call_llm returns a raw dict or an object, adapt this line:
        raw_text = response["candidates"][0]["content"]["parts"][0]["text"]

        # 3. Use Regex to cleanly extract just the JSON string within the markdown code blocks
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        
        if json_match:
            extracted_json_str = json_match.group(1)
            # 4. Parse the extracted string into a standard Python dictionary
            structured_data = json.loads(extracted_json_str)
            return structured_data
        else:
            # Fallback if the LLM outputted raw JSON without markdown blocks
            return json.loads(raw_text)

    except Exception as e:
        return {"status": "failure", "reason": str(e)}


async def process_antenna_radiation(
    file_path: str,
    clusters_dict: dict,  # The serialized dictionary from label_dxf_clusters
    matched_index_str: str,
    azimuth_deg: float,
    radiation_len: float = 2000.0
) -> str:
    """
    Opens the existing DXF file, locates the target cluster, calculates its 
    front face boundary, backs away 600mm from that face, and fires radiation rays.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Target DXF file not found at: {file_path}")

    if matched_index_str not in clusters_dict:
        print(f"Target index {matched_index_str} is missing from labeled clusters dictionary.")
        return file_path

    target_antenna_data = clusters_dict[matched_index_str]
    center_x, center_y = target_antenna_data["center"]
    bbox = target_antenna_data["bounding_box"]
    
    # 1. Calculate the antenna's physical bounding dimensions
    antenna_width = bbox["max_x"] - bbox["min_x"]
    antenna_height = bbox["max_y"] - bbox["min_y"]
    
    # 2. Translate Telecom Azimuth to CAD standard polar radians
    math_theta = math.radians(90.0 - azimuth_deg)
    
    # 3. Determine how far the front face extends from the center point
    # We find the intersection distance along the directional vector to the bounding box edge
    cos_t = math.cos(math_theta)
    sin_t = math.sin(math_theta)
    
    # Distance from center to the bounding edges along our facing vector
    dist_x = abs((antenna_width / 2.0) / cos_t) if abs(cos_t) > 1e-5 else float('inf')
    dist_y = abs((antenna_height / 2.0) / sin_t) if abs(sin_t) > 1e-5 else float('inf')
    
    # The actual distance from center to the front face plane
    distance_to_front_face = min(dist_x, dist_y)
    
    # 4. Calculate the net displacement from the center point:
    # To end up 600mm BEHIND the front face, our position relative to the center is:
    # Net Shift = (Distance to Front Face) - 600.0mm
    net_shift = distance_to_front_face - 300.0
    
    # 5. Apply the net shift along the facing vector to find the source point
    source_x = center_x + net_shift * cos_t
    source_y = center_y + net_shift * sin_t
    source_pt = (source_x, source_y)
    
    # 6. Open the DXF to draw the geometry layers
    doc = ezdxf.readfile(file_path)
    msp = doc.modelspace()
    
    rad_layer = "ANTENNA_RADIATION"
    if rad_layer not in doc.layers:
        doc.layers.new(name=rad_layer, dxfattribs={'color': 1}) # Red layer
        
    # Compute radiation cone vector limits (+/- 60 degrees from centerline)
    angle_plus_60 = math_theta + math.radians(60.0)
    angle_minus_60 = math_theta - math.radians(60.0)
    
    ray1_end = (
        source_x + radiation_len * math.cos(angle_plus_60),
        source_y + radiation_len * math.sin(angle_plus_60)
    )
    ray2_end = (
        source_x + radiation_len * math.cos(angle_minus_60),
        source_y + radiation_len * math.sin(angle_minus_60)
    )
    
    # 7. Add lines and arc visualization to the CAD modelspace
    msp.add_line(start=source_pt, end=ray1_end, dxfattribs={'layer': rad_layer})
    msp.add_line(start=source_pt, end=ray2_end, dxfattribs={'layer': rad_layer})
    
    deg_start = math.degrees(angle_minus_60)
    deg_end = math.degrees(angle_plus_60)
    msp.add_arc(
        center=source_pt,
        radius=radiation_len / 2.0,
        start_angle=deg_start,
        end_angle=deg_end,
        dxfattribs={'layer': rad_layer}
    )
    
    # 8. Commit and save file structural changes
    doc.saveas(file_path)
    return file_path

def get_significant_vertices(
    file_path: str,
    layer_name: str = "STEELWORK",
    min_member_length: float = 300.0,   # discard anything shorter — bolt ticks are 2–12 units
    joint_cluster_dist: float = 200.0,  # endpoints this close = same physical joint
    min_degree: int = 2,                # keep joints where >= N structural members meet
) -> list:
    """
    Extracts the true structural joint vertices from the steelwork layer.

    The old approach walked every segment and detected angle changes, but the
    STEELWORK layer contains ~660 entities — most of them bolt-hole circles,
    2mm annotation ticks, and closed hexagonal bolt symbols.  Every one of those
    started a fresh traversal chain and dumped 2 phantom vertices into the result.

    This approach works in three steps:
      1. FILTER  — keep only LINE / open-LWPOLYLINE entities whose length is
                   >= min_member_length.  Structural beams are 300-3000+ units;
                   all detail noise is under 50 units.  One threshold eliminates
                   hundreds of false positives.
      2. CLUSTER — collect the two endpoints of each surviving member, then merge
                   endpoints within joint_cluster_dist into a single joint
                   (centroid-averaged).  Steel connection nodes have physical width;
                   the two flanges of an I-beam are drawn 150 mm apart — clustering
                   collapses them into one point.
      3. DEGREE  — count how many member-endpoints fell into each cluster.  A real
                   structural joint has >= min_degree members meeting.  Degree-1
                   clusters are isolated stubs and are discarded.

    Returns a list of (x, y) tuples sorted by degree descending.
    """
    doc = ezdxf.readfile(file_path)
    msp = doc.modelspace()

    # ── Step 1 & 2: collect endpoints from structural members only ──────────
    endpoints: list = []

    for entity in msp.query(f'*[layer=="{layer_name}"]'):
        dt = entity.dxftype()

        if dt == 'LINE':
            s = (entity.dxf.start.x, entity.dxf.start.y)
            e = (entity.dxf.end.x, entity.dxf.end.y)
            if math.hypot(e[0] - s[0], e[1] - s[1]) >= min_member_length:
                endpoints.extend([s, e])

        elif dt in ('LWPOLYLINE', 'POLYLINE'):
            if entity.closed:
                continue  # closed shapes are bolt symbols / gusset plates — never a joint
            pts = [(v[0], v[1]) for v in entity.get_points()]
            if len(pts) < 2:
                continue
            # Walk sub-segments so genuine direction-change kinks inside a polyline
            # are also counted as joint candidates
            for i in range(len(pts) - 1):
                seg_len = math.hypot(pts[i+1][0] - pts[i][0], pts[i+1][1] - pts[i][1])
                if seg_len >= min_member_length:
                    endpoints.extend([pts[i], pts[i+1]])

        # CIRCLEs and ARCs represent bolt holes / pipe ends — intentionally ignored

    # ── Step 3: cluster nearby endpoints → one entry per physical joint ─────
    assigned = [False] * len(endpoints)
    clusters = []  # (cx, cy, degree)

    for i, pt in enumerate(endpoints):
        if assigned[i]:
            continue
        group = [pt]
        assigned[i] = True
        for j in range(i + 1, len(endpoints)):
            if not assigned[j] and math.hypot(pt[0] - endpoints[j][0], pt[1] - endpoints[j][1]) < joint_cluster_dist:
                group.append(endpoints[j])
                assigned[j] = True
        cx = sum(p[0] for p in group) / len(group)
        cy = sum(p[1] for p in group) / len(group)
        clusters.append((cx, cy, len(group)))

    # ── Step 4: filter by degree, sort highest-degree first, return (x, y) ──
    joints_with_deg = [(cx, cy, deg) for cx, cy, deg in clusters if deg >= min_degree]
    joints_with_deg.sort(key=lambda v: (-v[2], v[1], v[0]))

    return [(cx, cy) for cx, cy, deg in joints_with_deg]

async def label_structural_vertices(file_path: str, layer_name: str = "STEELWORK", text_height: float = 80.0, offset_distance: float = 15.0) -> dict:
    """
    Computes key structural anchors, maps them to sequential P-keys, 
    and writes them to the VERTEX_LABELS layer inside the DXF document.
    """
    vertices = get_significant_vertices(file_path, layer_name=layer_name)
    
    doc = ezdxf.readfile(file_path)
    msp = doc.modelspace()
    
    label_layer = "VERTEX_LABELS"
    if label_layer not in doc.layers:
        doc.layers.new(name=label_layer, dxfattribs={'color': 3}) # Green color attribute

    vertex_map = {}
    for idx, (vx, vy) in enumerate(vertices):
        point_key = f"P{idx + 1}"
        vertex_map[point_key] = [float(vx), float(vy)]
        
        # Add text label to modelspace with an visual offset
        msp.add_text(
            text=point_key,
            dxfattribs={
                'layer': label_layer,
                'height': text_height,
                'insert': (vx + offset_distance, vy + offset_distance)
            }
        )
    
    doc.saveas(file_path) # Overwrite in-place to carry over modifications
    return vertex_map

async def snapshot_steelwork_and_labels(
    dxf_path: str, 
    output_dir: str = "dxf_snap", 
    max_edge_pixels: int = 2048
) -> str:
    """
    Renders a high-contrast PNG snippet displaying ONLY the STEELWORK 
    and the new VERTEX_LABELS layer, isolating it completely from old equipment clutter.
    """
    if not os.path.exists(dxf_path):
        raise HTTPException(status_code=404, detail="Target DXF file not found.")
        
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    # CRITICAL STEP: Turn off all layers EXCEPT Steelwork and the Labels
    # This prevents old equipment from confusing the VLLM
    allowed_layers = {"STEELWORK", "VERTEX_LABELS"}
    for layer in doc.layers:
        if layer.dxf.name not in allowed_layers:
            layer.off() # Temporarily hide layer visually

    # Calculate scene boundaries from remaining active layers
    all_scene_points = []
    for entity in msp.query('*[layer=="STEELWORK"]'):
        all_scene_points.extend(extract_entity_vertices(entity))
        
    if not all_scene_points:
        raise HTTPException(status_code=422, detail="No visible structural framework found to frame image snippet.")
        
    scene_arr = np.array(all_scene_points)
    s_min_x, s_min_y = np.min(scene_arr, axis=0)
    s_max_x, s_max_y = np.max(scene_arr, axis=0)
    
    margin = 500.0  # Safe visual framing buffer
    width = (s_max_x - s_min_x) + (margin * 2)
    height = (s_max_y - s_min_y) + (margin * 2)
    
    render_box = BoundingBox([
        (s_min_x - margin, s_min_y - margin), 
        (s_max_x + margin, s_max_y + margin)
    ])
    
    # Calculate performance safe DPI resolution limit dynamically
    max_drawing_units = max(width, height)
    calculated_dpi = int((max_edge_pixels / max_drawing_units) * 72)
    calculated_dpi = max(min(calculated_dpi, 300), 45)
    
    # Execute rendering backend workflow via PyMuPDF 
    ctx = RenderContext(doc)
    backend = pymupdf.PyMuPdfBackend()
    Frontend(ctx, backend).draw_layout(msp)
    
    ppm_bytes = backend.get_pixmap_bytes(
        page=layout.Page(0, 0),
        fmt="ppm",
        dpi=calculated_dpi,
        render_box=render_box
    )

    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    dxf_filename = os.path.basename(dxf_path)  
    dxf_name = os.path.splitext(dxf_filename)[0]
    output_png_path = f"{output_dir}/{dxf_name}_isolated.png"
    
    with io.BytesIO(ppm_bytes) as stream:
        with Image.open(stream, formats=["ppm"]) as img:
            img.save(output_png_path, format="PNG")
            
    return output_png_path



async def auto_analyze_drawing(file: str, img: str, input_params: str):
    # This wrapper can call the cluster logic and then label the output
    labeled_file_path = await label_dxf_clusters(file_path=file)
    snapshot_path = await label_and_snapshot_dxf(dxf_path=labeled_file_path["output_path"])

    # ant = await get_antenna(img, snapshot_path["saved_snapshot"], input_params)

    ant = {
  "status": "Success",
  "matched_index": "antenna_4",
  "reasoning": "The target antenna is an AIR 3258 at a height of 20.24m with an azimuth of 340°. In Image B, this antenna (labeled E2) is located at the top-most position of the headframe. Cross-referencing this exact physical position on Image A maps directly to the label antenna_5."
}

    matched_index = ant.get("matched_index")
    
    if ant.get("status") == "Success" and matched_index:
        # Pull numeric azimuth out of input text parameter variables using regular expressions
        azimuth_val = 0.0
        azimuth_match = re.search(r"azimuth(?: of)?\s*:?\s*(\d+)", input_params, re.IGNORECASE)
        if azimuth_match:
            azimuth_val = float(azimuth_match.group(1))
        else:
            # Fallback to scan inside Gemini's reasoning string if parameter pattern mismatches
            reason_match = re.search(r"azimuth of (\d+)", ant.get("reasoning", ""), re.IGNORECASE)
            if reason_match:
                azimuth_val = float(reason_match.group(1))

        # 6. Execute the radiation modeler, overwriting the file in-place
        final_dxf_path = await process_antenna_radiation(
            file_path=labeled_file_path["output_path"],
            clusters_dict=labeled_file_path["clusters"],
            matched_index_str=matched_index,
            azimuth_deg=azimuth_val
        )
        
        # Keep response models in sync with the file system mutations
        labeled_file_path["output_path"] = final_dxf_path

        vertex_dictionary = await label_structural_vertices(file_path=labeled_file_path["output_path"])
        steelwork_label_path = await snapshot_steelwork_and_labels(labeled_file_path["output_path"])


    return {
        "status": "success", 
        "saved_file": labeled_file_path["output_path"], 
        "snapshot": snapshot_path, 
        "antenna_identification": ant,
        "steelwork_labelled_path": steelwork_label_path
    }