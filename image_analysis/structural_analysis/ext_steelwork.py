import math
import numpy as np
import ezdxf

def get_line_intersection(line1_start, line1_end, line2_start, line2_end):
    """
    Calculates the 2D intersection point between two line segments.
    Returns (x, y) if an intersection exists on both segments, otherwise None.
    """
    x1, y1 = line1_start
    x2, y2 = line1_end
    x3, y3 = line2_start
    x4, y4 = line2_end

    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) < 1e-6:
        return None  # Parallel lines

    # Intersection point parameter t for line1
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denominator
    # Intersection point parameter u for line2
    u = ((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denominator

    # Verify if the intersection point lies within both line segments
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        ix = x1 + t * (x2 - x1)
        iy = y1 + t * (y2 - y1)
        return (ix, iy)
        
    return None

def sample_points_along_segment(p1, p2, step_mm=100.0):
    """Linearly interpolates points along a rail segment given a fixed interval step."""
    x1, y1 = p1
    x2, y2 = p2
    length = math.hypot(x2 - x1, y2 - y1)
    
    if length == 0:
        return [p1]
        
    num_steps = int(length / step_mm)
    points = []
    for i in range(num_steps + 1):
        t = (i * step_mm) / length
        if t > 1.0: t = 1.0
        px = x1 + t * (x2 - x1)
        py = y1 + t * (y2 - y1)
        points.append((px, py))
    return points

# async def extract_outer_steelwork_points(file_path: str, layer_name: str = "STEELWORK", step_mm: float = 100.0) -> list:
#     """
#     Parses the DXF file, reads the raw lines from the targeted layer, and performs
#     an inward Ray-Casting sweep to isolate only the outermost rails, returning 
#     discrete candidate points sampled along those lines.
#     """
#     try:
#         doc = ezdxf.readfile(file_path)
#     except (IOError, ezdxf.DXFStructureError):
#         raise HTTPException(status_code=400, detail="Invalid, missing, or corrupted DXF file.")

#     msp = doc.modelspace()
#     all_steel_segments = []
#     all_raw_points = []

#     # 1. Gather all line-segments from the target STEELWORK layer
#     query_str = f'*[layer=="{layer_name}"]'
#     for entity in msp.query(query_str):
#         dxftype = entity.dxftype()
#         if dxftype == 'LINE':
#             seg = ((entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y))
#             all_steel_segments.append(seg)
#             all_raw_points.extend(seg)
#         elif dxftype in ('LWPOLYLINE', 'POLYLINE'):
#             vertices = [(v[0], v[1]) for v in entity.get_points()]
#             for i in range(len(vertices) - 1):
#                 seg = (vertices[i], vertices[i+1])
#                 all_steel_segments.append(seg)
#                 all_raw_points.extend(seg)

#     if not all_steel_segments:
#         raise HTTPException(status_code=404, detail=f"No geometry found on layer '{layer_name}'.")

#     # 2. Determine structural center of mass and outer perimeter boundary radius
#     pts_arr = np.array(all_raw_points)
#     center_x, center_y = np.mean(pts_arr, axis=0)
    
#     min_x, min_y = np.min(pts_arr, axis=0)
#     max_x, max_y = np.max(pts_arr, axis=0)
#     max_dimension = max(max_x - min_x, max_y - min_y)
#     # Put the ray source radius safely outside the entire structure layout box
#     ray_source_radius = max_dimension * 1.5

#     outer_rail_segments = set()

#     # 3. Perform a 360-degree ray sweep inward (adjust angle_step for sensitivity)
#     angle_step = 1.0  # Check every 1 degree
#     for angle_deg in np.arange(0.0, 360.0, angle_step):
#         rad = math.radians(angle_deg)
#         # Position a remote start point far outside looking in
#         ray_start = (center_x + ray_source_radius * math.cos(rad), center_y + ray_source_radius * math.sin(rad))
#         ray_end = (center_x, center_y)

#         closest_intersection_dist = float('inf')
#         hit_segment = None

#         # Look for the closest line intersection encountered along this specific ray path
#         for seg in all_steel_segments:
#             pt_int = get_line_intersection(ray_start, ray_end, seg[0], seg[1])
#             if pt_int:
#                 dist = math.hypot(pt_int[0] - ray_start[0], pt_int[1] - ray_start[1])
#                 if dist < closest_intersection_dist:
#                     closest_intersection_dist = dist
#                     hit_segment = seg

#         if hit_segment:
#             outer_rail_segments.add(hit_segment)

#     # 4. Generate the flat array of discrete linear coordinate candidates from matching outer rails
#     candidate_points = []
#     for seg in outer_rail_segments:
#         sampled_pts = sample_points_along_segment(seg[0], seg[1], step_mm=step_mm)
#         candidate_points.extend(sampled_pts)

#     # De-duplicate matching coordinates sharing overlapping spaces down to a single index
#     unique_candidates = list(set((round(p[0], 2), round(p[1], 2)) for p in candidate_points))
#     return unique_candidates

async def extract_outer_steelwork_points(file_path: str, layer_name: str = "STEELWORK", step_mm: float = 100.0) -> list:
    """
    Parses the DXF file, performs an inward Ray-Casting sweep, and applies a
    spatial depth filter to eliminate lingering internal cross-bracing segments.
    """
    try:
        doc = ezdxf.readfile(file_path)
    except (IOError, ezdxf.DXFStructureError):
        return []

    msp = doc.modelspace()
    all_steel_segments = []
    all_raw_points = []

    # 1. Gather all line-segments from the target STEELWORK layer
    query_str = f'*[layer=="{layer_name}"]'
    for entity in msp.query(query_str):
        dxftype = entity.dxftype()
        if dxftype == 'LINE':
            seg = ((entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y))
            all_steel_segments.append(seg)
            all_raw_points.extend(seg)
        elif dxftype in ('LWPOLYLINE', 'POLYLINE'):
            vertices = [(v[0], v[1]) for v in entity.get_points()]
            for i in range(len(vertices) - 1):
                seg = (vertices[i], vertices[i+1])
                all_steel_segments.append(seg)
                all_raw_points.extend(seg)

    if not all_steel_segments:
        return []

    # 2. Determine structural center of mass and outer perimeter boundary radius
    pts_arr = np.array(all_raw_points)
    center_x, center_y = np.mean(pts_arr, axis=0)
    
    min_x, min_y = np.min(pts_arr, axis=0)
    max_x, max_y = np.max(pts_arr, axis=0)
    max_dimension = max(max_x - min_x, max_y - min_y)
    ray_source_radius = max_dimension * 1.5

    outer_rail_segments = set()

    # 3. Perform a 360-degree ray sweep inward
    angle_step = 0.5  # Increased resolution to 0.5 for tight outrigger corners
    for angle_deg in np.arange(0.0, 360.0, angle_step):
        rad = math.radians(angle_deg)
        ray_start = (center_x + ray_source_radius * math.cos(rad), center_y + ray_source_radius * math.sin(rad))
        ray_end = (center_x, center_y)

        closest_intersection_dist = float('inf')
        hit_segment = None

        for seg in all_steel_segments:
            pt_int = get_line_intersection(ray_start, ray_end, seg[0], seg[1])
            if pt_int:
                dist = math.hypot(pt_int[0] - ray_start[0], pt_int[1] - ray_start[1])
                if dist < closest_intersection_dist:
                    closest_intersection_dist = dist
                    hit_segment = seg

        if hit_segment:
            # --- CRITICAL FILTER CHANGE ---
            # Calculate the midpoint of the hit segment
            seg_mid_x = (hit_segment[0][0] + hit_segment[1][0]) / 2.0
            seg_mid_y = (hit_segment[0][1] + hit_segment[1][1]) / 2.0
            dist_to_center = math.hypot(seg_mid_x - center_x, seg_mid_y - center_y)
            
            # If the segment is lingering too close to the dead center of mass,
            # it's an internal cross-brace or a platform grating element. Skip it!
            if dist_to_center > (max_dimension * 0.18): 
                outer_rail_segments.add(hit_segment)

    # 4. Generate the flat array of discrete coordinate candidates
    candidate_points = []
    for seg in outer_rail_segments:
        sampled_pts = sample_points_along_segment(seg[0], seg[1], step_mm=step_mm)
        candidate_points.extend(sampled_pts)

    # Clean coordinates by snap-rounding to the nearest whole millimeter unit to stop pixel drift
    unique_candidates = list(set((int(round(p[0])), int(round(p[1]))) for p in candidate_points))
    return unique_candidates