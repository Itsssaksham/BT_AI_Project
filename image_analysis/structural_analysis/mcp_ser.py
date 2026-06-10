from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import base64
import requests
import json
from typing import Optional, Dict, Any
import re
import os
from shapely.geometry import Polygon, LineString

import ezdxf
import math

import cv2
import numpy as np
import easyocr

from call_claude import call_claude

def extract_json(text: str):
    # remove markdown ```json ``` wrappers if present
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError("No JSON found")


def scale_mcp_data_in_place(data: dict):
    """
    Scales all raw pixel coordinates by the calibration scale factor 
    and converts them directly into CAD space metrics.
    """
    scale = data["calibration"].get("scale", 1.0)
    if scale < 1.0: 
        scale = 15.0 

    # 1. Scale Headframe vertices
    if "headframe" in data and "vertices" in data["headframe"]:
        data["headframe"]["vertices"] = [
            [v[0] * scale, v[1] * -scale] for v in data["headframe"]["vertices"]
        ]

    # 2. Scale Poles coordinates
    if "poles" in data and isinstance(data["poles"], list):
        for pole in data["poles"]:
            if "from" in pole and pole["from"]:
                pole["from"] = [pole["from"][0] * scale, pole["from"][1] * -scale]
            if "to" in pole and pole["to"]:
                pole["to"] = [pole["to"][0] * scale, pole["to"][1] * -scale]
            if "pole_tip_px" in pole and pole["pole_tip_px"]:
                pole["pole_tip_px"] = [pole["pole_tip_px"][0] * scale, pole["pole_tip_px"][1] * -scale]

    # 3. Scale Occupancy Map equipment vertices
    if "occupancy_map" in data and isinstance(data["occupancy_map"], list):
        for item in data["occupancy_map"]:
            if "vertices" in item and item["vertices"]:
                item["vertices"] = [
                    [v[0] * scale, v[1] * -scale] for v in item["vertices"]
                ]
            if "pole_tip_px" in item and item["pole_tip_px"]:
                item["pole_tip_px"] = [item["pole_tip_px"][0] * scale, item["pole_tip_px"][1] * -scale]

    # Set scale to 1.0 globally so downstream components don't re-scale
    data["calibration"]["scale"] = 1.0
    return data

async def run_pipeline(image_path):
    from ltbt import logger

    
    # Step 2: Formulate Prompt with explicit rules for clean mapping classification
    prompt = """
    I am providing you a plan-view sketch of a telecom tower headframe.

Your task is to:
1. Detect and return the exact pixel coordinates of the headframe structure
2. Detect and return azimuth-aligned oriented bounding boxes for every piece of equipment visible (antennas, microwave dishes, radios, MHAs, GPS units, poles, or any other mounted equipment)

---

## STEP-BY-STEP INSTRUCTIONS

### STEP 1 — Calibration
- Identify any scale bar or drawing scale annotation (e.g. "SCALE 1:50")
- Identify image DPI if available (assume 300 DPI if not stated)
- Compute: `pixel_to_mm_factor = (25.4 / DPI) * scale_denominator`
- Example: Scale 1:50 at 300 DPI → `(25.4/300) * 50 = 4.2333 mm/px`

### STEP 2 — Headframe
- The headframe is the central structural frame (triangle, rectangle, circle, polygon, or any shape)
- Identify every vertex or key boundary point of the headframe outline
- For a triangle: return 3 vertices
- For a rectangle/polygon: return all corner vertices in order
- For a circle: return centre point + radius
- Also identify each NODE (junction point) where equipment poles attach to the headframe

### STEP 3 — Equipment Poles
- Each piece of equipment is mounted on its own dedicated pole that extends outward from a headframe node
- Identify the pole root (at the headframe node) and pole tip (where equipment mounts) for every pole
- Multiple poles can share the same node but must diverge in different azimuth directions

### STEP 4 — Equipment Bounding Boxes (CRITICAL RULES)
For every piece of equipment detected (antenna, dish, radio, MHA, GPS, RRU, or any other item):

**Rule 1 — Azimuth Alignment**
The bounding box must be ROTATED to align with the equipment's azimuth angle:
- The BACK FACE of the box must be flush against the pole tip (the mount point)
- The box extends OUTWARD from the pole tip in the azimuth direction
- Use a rotated quadrilateral (4 vertices), not an axis-aligned rectangle

**Rule 2 — Back Face at Pole Tip**
The back face centre = pole tip coordinate (NOT the headframe node).
Each pole has its own tip offset from the node:
`pole_tip = (node_x + sin(az°) * pole_length_px, node_y - cos(az°) * pole_length_px)`
Typical pole_length_px: measure from drawing or estimate ~15px if not visible.

**Rule 3 — No Overlapping Boxes**
No two equipment boxes may overlap. If two items share a node, they are on SEPARATE poles that diverge in different directions. Verify each pair of boxes at shared nodes for overlap and adjust pole offsets if needed.

**Rule 4 — Oriented Corner Computation**
Given pole tip (tx, ty), azimuth az°, box width W (perpendicular to beam), box depth D (along beam):
```
fwd  = (sin(az°), -cos(az°))       # forward direction in image (y-down)
side = (cos(az°),  sin(az°))       # perpendicular direction
back-left  = [tx - side*W/2,       ty - side_y*W/2      ]
back-right = [tx + side*W/2,       ty + side_y*W/2      ]
front-right= [tx + side*W/2 + fwd*D, ty + side_y*W/2 + fwd_y*D]
front-left = [tx - side*W/2 + fwd*D, ty - side_y*W/2 + fwd_y*D]
```
Return vertices in order: [back-left, back-right, front-right, front-left]

**Rule 5 — Equipment Type Recognition**
Identify each item from its visual shape and any label text:
- **Antenna** — elongated rectangular body, labelled A1/A2/B1/B2 etc.
- **Dish / Microwave** — circular or square dish symbol, labelled D1/MW etc.
- **MHA** (Mast Head Amplifier) — small box, usually grouped 3-per-sector on poles
- **RRU / Radio** — rectangular radio unit, often labelled RRU or R
- **GPS** — small dome or stub antenna, usually at top of structure
- **Any unlabelled item** — include it with type "Unknown" and best-guess dimensions

---
## OUTPUT FORMAT
Return ONLY a raw JSON object. No prose, no markdown fences.
JSON structure:
{
  "calibration": {
    "pixel_to_mm_factor": 0.0,
    "assumed_dpi": 300,
    "drawing_scale": "1:50",
    "image_size_px": [width, height]
  },
  "headframe": {
    "shape": "triangle | rectangle | polygon | circle",
    "vertices": [[x, y], [x, y], [x, y]],
    "radius_px": null,
    "nodes": {
      "NODE_ID": [x, y]
    }
  },
  "poles": [
    {
      "id": "pole_A1",
      "from_node": "NODE_ID",
      "root_px": [x, y],
      "tip_px": [x, y],
      "azimuth": 0,
      "equipment_id": "A1"
    }
  ],
  "occupancy_map": [
    {
      "id": "A1",
      "type": "Antenna | Dish | MHA | Radio | RRU | GPS | Unknown",
      "label": "text label from drawing if any",
      "sector": "A | B | C | null",
      "azimuth": 0,
      "mount_node": "NODE_ID",
      "pole_tip_px": [x, y],
      "vertices": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]],
      "width_px": 0,
      "depth_px": 0
    }
  ]
}

## VERIFICATION CHECKLIST (perform before returning output)
- [ ] Every equipment box back face is at its pole tip — not floating, not at the node
- [ ] No two equipment boxes overlap (check all pairs at shared nodes)
- [ ] Every box is rotated to match its azimuth — no axis-aligned boxes for non-0°/90° azimuths
- [ ] Every visible piece of equipment in the drawing has an entry
- [ ] Headframe node coordinates match the triangle/polygon vertex scan
- [ ] Pole root coordinates are ON the headframe boundary

"""
    try:
    # Step 3: Run Claude Agent orchestration parsing
        claude_response = await call_claude(prompt,[image_path])

    # try:
    #     # ── Extract raw text ───────────────────────────────────────
    #         text = (
    #             gemini_json["candidates"][0]["content"]["parts"][0]["text"]
    #             .strip()
    #         )

    #         # ── Aggressive cleaning ────────────────────────────────────
    #         # Remove all common markdown code fences (multiple variants)
    #         text = re.sub(r'^(```(?:json)?\s*|\s*```json\s*)', '', text, flags=re.IGNORECASE | re.MULTILINE)
    #         text = re.sub(r'(\s*```)$', '', text, flags=re.MULTILINE)

    #         # Remove any leading/trailing backticks that survived
    #         text = text.strip('` \n\r')

    #         # Remove markdown bold/italic that sometimes leaks in
    #         text = re.sub(r'\*+([^*]+)\*+', r'\1', text)

    #         # Final strip
    #         text = text.strip()

    #         if not text:
    #             raise ValueError("Empty text after cleaning")

    #         # ── Parse ──────────────────────────────────────────────────
    #         ret_json = json.loads(text)
            
    #         if "calibration" not in ret_json or "headframe" not in ret_json or "occupancy_map" not in ret_json:
    #             raise ValueError("Missing required keys in output JSON")


    #         return {
    #             "calibration": ret_json.get("calibration"),
    #             "headframe": ret_json.get("headframe"),
    #             "occupancy_map": ret_json.get("occupancy_map"),
    #             "notes": ret_json.get("notes", "")
    #         }

        return claude_response
            
    except Exception as e:
            logger.exception(f"Failed to parse page number for tpv sketch - raw response:  error: {str(e)}")
            return {
                "calibration": {},
                "headframe": {},
                "occupancy_map": [],
                "notes": f"Gemini parsing failed: {str(e)}"
            }


def generate_dxf_from_json(data, filename="output_sketch.dxf"):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    
    # 1. Draw the Headframe Structure (Data is already scaled!)
    mm_h_verts = data["headframe"]["vertices"]
    msp.add_lwpolyline(mm_h_verts, close=True, dxfattribs={"layer": "STRUCTURE", "color": 7})

    if "poles" in data and isinstance(data["poles"], list):
        for pole in data["poles"]:
            p_from = pole.get("from")
            p_to = pole.get("to")
            
            if p_from and p_to:
                msp.add_line(
                    p_from, 
                    p_to, 
                    dxfattribs={"layer": "POLES", "color": 8}
                )

    # 2. Draw each piece of equipment
    for item in data["occupancy_map"]:
        mm_eq_verts = item.get("vertices", [])
        if len(mm_eq_verts) < 3:
            continue
            
        color = 1 if "Antenna" in item["type"] else 5
        msp.add_lwpolyline(mm_eq_verts, close=True, dxfattribs={"layer": "EQUIPMENT", "color": color})

        cx = sum(v[0] for v in mm_eq_verts) / len(mm_eq_verts)
        cy = sum(v[1] for v in mm_eq_verts) / len(mm_eq_verts)
        
        msp.add_text(item["id"], dxfattribs={"height": 40, "color": 7}).set_placement((cx, cy))

    doc.saveas(filename)
    return filename


def get_sector_geometry(h_verts):
    """Dynamically identifies sectors based on headframe rail segments."""
    sectors = []
    num_verts = len(h_verts)
    for i in range(num_verts):
        v1 = h_verts[i]
        v2 = h_verts[(i + 1) % num_verts]
        
        # Calculate standard azimuth based on rail orientation (perpendicular outward)
        rail_angle = math.degrees(math.atan2(v2[1] - v1[1], v2[0] - v1[0]))
        sector_azimuth = (rail_angle - 90) % 360
        
        sectors.append({
            "id": chr(65 + i), # A, B, C...
            "azimuth": sector_azimuth,
            "seg": (v1, v2)
        })
    return sectors


def check_radiation_interference(new_ant_poly, radiation_lines, existing_polys):
    """Checks if any existing equipment intersects the new antenna or its radiation cone."""
    for existing in existing_polys:
        if new_ant_poly.intersects(existing):
            return True # Physical collision
        for rad_line in radiation_lines:
            if rad_line.intersects(existing):
                return True # Radiation obstruction
    return False


def get_antenna_offset_params(rail_start, rail_end, antenna_verts):
    """Calculates how an existing antenna is 'attached' to its rail."""
    # Rail vector and length
    dx, dy = rail_end[0] - rail_start[0], rail_end[1] - rail_start[1]
    mag = math.sqrt(dx**2 + dy**2)
    ux, uy = dx/mag, dy/mag
    
    # Antenna center
    acx = sum(v[0] for v in antenna_verts) / 4
    acy = sum(v[1] for v in antenna_verts) / 4
    
    # Project center onto rail to find the perpendicular offset
    # Vector from rail_start to antenna center
    vax, vay = acx - rail_start[0], acy - rail_start[1]
    # Dot product to find distance along rail
    dist_along = vax * ux + vay * uy
    # Perpendicular point on rail
    proj_x, proj_y = rail_start[0] + dist_along * ux, rail_start[1] + dist_along * uy
    
    # The actual offset vector from rail to center
    offset_x, offset_y = acx - proj_x, acy - proj_y
    
    # Relative vertices from antenna center
    rel_verts = [(v[0] - acx, v[1] - acy) for v in antenna_verts]
    
    return offset_x, offset_y, rel_verts


def find_consistent_placement(rail_start, rail_end, ox, oy, rel_verts, existing_polys, hf_centroid):
    """
    Slides the antenna along the rail, ensuring:
    1. 500mm physical clearance from all existing equipment.
    2. The 120° radiation lines (firing from 300mm behind the back face) 
       do not cross or intersect any existing equipment footprints.
    """
    dx, dy = rail_end[0] - rail_start[0], rail_end[1] - rail_start[1]
    rail_length = math.sqrt(dx**2 + dy**2)
    ux, uy = dx/rail_length, dy/rail_length
    
    # 50mm step resolution for finding space along the mm-scaled rail structure
    step_size = 50 
    
    for d in range(int(rail_length * 0.1), int(rail_length * 0.9), step_size):
        rail_px = rail_start[0] + (ux * d)
        rail_py = rail_start[1] + (uy * d)
        
        target_cx, target_cy = rail_px + ox, rail_py + oy
        candidate_verts = [(target_cx + rx, target_cy + ry) for rx, ry in rel_verts]
        candidate_poly = Polygon(candidate_verts)
        
        # --- TEST 1: 500mm PHYSICAL CLEARANCE ---
        clearance_zone = candidate_poly.buffer(500.0)
        physical_conflict = False
        for existing in existing_polys:
            if clearance_zone.intersects(existing):
                physical_conflict = True
                break
        
        if physical_conflict:
            continue  # Blocked physically, skip to next sliding position
            
        # --- TEST 2: RADIATION INTERFERENCE CROSSFIRE ---
        # Generate the ray trajectories for this specific temporary test spot
        rad_lines = generate_test_radiation_rays(candidate_verts, hf_centroid)
        
        radiation_conflict = False
        for existing in existing_polys:
            for ray in rad_lines:
                if ray.intersects(existing):
                    radiation_conflict = True
                    break
            if radiation_conflict:
                break
                
        # If it passes both the 500mm clearance envelope AND radiation paths are clear
        if not radiation_conflict:
            return target_cx, target_cy, candidate_verts
            
    return None, None, None


def generate_test_radiation_rays(antenna_verts, hf_centroid, length_mm=3000):
    """
    Generates Shapely LineString paths starting 550mm behind the front face 
    to verify line-of-sight clearance during layout optimization.
    """
    sorted_verts = sorted(
        antenna_verts, 
        key=lambda v: (v[0]-hf_centroid[0])**2 + (v[1]-hf_centroid[1])**2, 
        reverse=True
    )
    
    p1, p2 = sorted_verts[0], sorted_verts[1]
    mx_front, my_front = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    nx, ny = -dy, dx
    
    ax_center = sum(v[0] for v in antenna_verts) / 4
    ay_center = sum(v[1] for v in antenna_verts) / 4
    
    if ((mx_front + nx - ax_center)**2 + (my_front + ny - ay_center)**2) < \
       ((mx_front - nx - ax_center)**2 + (my_front - ny - ay_center)**2):
        nx, ny = -nx, -ny
        
    normal_length = math.sqrt(nx**2 + ny**2)
    ux, uy = nx / normal_length, ny / normal_length
    
    # Ray starts 550mm behind the front face midpoint
    origin_x = mx_front - (ux * 550.0)
    origin_y = my_front - (uy * 550.0)
    
    base_angle = math.atan2(uy, ux)
    total_ray_length = length_mm + 550.0
    
    rays = []
    for offset_deg in [-60, 60]:
        rad = base_angle + math.radians(offset_deg)
        ex = origin_x + total_ray_length * math.cos(rad)
        ey = origin_y + total_ray_length * math.sin(rad)
        rays.append(LineString([(origin_x, origin_y), (ex, ey)]))
        
    return rays



def add_dynamic_radiation_cone(msp, antenna_verts, hf_centroid, length_mm=3000):
    """
    Logic: Identifies the front face, calculates the outward normal direction,
    sets the ray origin 550mm directly behind the FRONT face, and projects rays 
    at +/- 60 degrees from that normal axis.
    """
    # 1. Sort vertices by distance to the headframe center
    # Farthest 2 are the front face, closest 2 are the back face
    sorted_verts = sorted(
        antenna_verts, 
        key=lambda v: (v[0]-hf_centroid[0])**2 + (v[1]-hf_centroid[1])**2, 
        reverse=True
    )
    
    # Front face midpoint (where the radiation parameters now anchor)
    p1, p2 = sorted_verts[0], sorted_verts[1]
    mx_front, my_front = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    
    # 2. Compute the outward-facing normal vector using the front face segment
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    nx, ny = -dy, dx
    
    # Verify the normal points AWAY from the antenna center. If it points inward, flip it.
    ax_center = sum(v[0] for v in antenna_verts) / 4
    ay_center = sum(v[1] for v in antenna_verts) / 4
    
    if ((mx_front + nx - ax_center)**2 + (my_front + ny - ay_center)**2) < \
       ((mx_front - nx - ax_center)**2 + (my_front - ny - ay_center)**2):
        nx, ny = -nx, -ny
        
    # 3. Convert normal to a unit vector (length of 1)
    normal_length = math.sqrt(nx**2 + ny**2)
    ux, uy = nx / normal_length, ny / normal_length
    
    # 4. Calculate the new ray origin point: 550mm BEHIND the FRONT face midpoint
    # Moving opposite to the outward normal means subtracting the vector component from the front face
    origin_x = mx_front - (ux * 550.0)
    origin_y = my_front - (uy * 550.0)
    
    # 5. Get the base angle of the normal vector
    base_angle = math.atan2(uy, ux)
    
    # 6. Draw the +/- 60 degree rays (Total 120° dispersion spread)
    # Total ray length extends from the new origin point inward/outward
    total_ray_length = length_mm + 550.0
    
    for offset_deg in [-60, 60]:
        rad = base_angle + math.radians(offset_deg)
        ex = origin_x + total_ray_length * math.cos(rad)
        ey = origin_y + total_ray_length * math.sin(rad)
        
        msp.add_line(
            (origin_x, origin_y), (ex, ey), 
            dxfattribs={"layer": "RADIATION_CONE", "color": 2, "linetype": "DASHED"}
        )


async def process_site_analysis(data, output_file="dynamic_analysis.dxf"):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    
    # 1. Headframe & Centroid (Data is already scaled!)
    h_verts = data["headframe"]["vertices"]
    msp.add_lwpolyline(h_verts, close=True, dxfattribs={"layer": "STRUCTURE", "color": 7})
    hf_centroid = (sum(v[0] for v in h_verts)/len(h_verts), sum(v[1] for v in h_verts)/len(h_verts))
    
    if "poles" in data and isinstance(data["poles"], list):
        for pole in data["poles"]:
            p_from = pole.get("from")
            p_to = pole.get("to")
            if p_from and p_to:
                msp.add_line(p_from, p_to, dxfattribs={"layer": "POLES", "color": 8})

    existing_polys = []
    for item in data["occupancy_map"]:
        eq_verts = item["vertices"]
        existing_polys.append(Polygon(eq_verts))
        color = 1 if "Antenna" in item["type"] else 5
        msp.add_lwpolyline(eq_verts, close=True, dxfattribs={"layer": "EXISTING", "color": color})

    # 2. Dynamic Sector Looping
    sectors = get_sector_geometry(h_verts)
    antennas = [item for item in data["occupancy_map"] if "Antenna" in item["type"]]
    if antennas:
        v = antennas[0]["vertices"]
        # Distance calculation without scale multiplication (already applied)
        w = math.sqrt((v[1][0]-v[0][0])**2 + (v[1][1]-v[0][1])**2)
        h = math.sqrt((v[2][0]-v[1][0])**2 + (v[2][1]-v[1][1])**2)
    else:
        w, h = 400, 200

    successful_sectors = []
    
    for sec in sectors:
        v1, v2 = sec["seg"]
    
        template = next((i for i in data["occupancy_map"] if i["id"].startswith(sec["id"]) and "Antenna" in i["type"]), None)
        if not template: 
            template = next((i for i in data["occupancy_map"] if "Antenna" in i["type"]), None)

        if template:
            t_verts = template["vertices"]
            ox, oy, rel_verts = get_antenna_offset_params(v1, v2, t_verts)
            # Look for this line inside your process_site_analysis function loop:
            cx, cy, final_verts = find_consistent_placement(
                v1, v2, ox, oy, rel_verts, existing_polys, hf_centroid
            )
            
            if cx:
                successful_sectors.append(sec["id"])
                msp.add_lwpolyline(final_verts, close=True, dxfattribs={"layer": "PROPOSED", "color": 3})
                add_dynamic_radiation_cone(msp, final_verts, hf_centroid)
                msp.add_text(f"NEW_{sec['id']}", dxfattribs={
                    "height": 40, "color": 3, "rotation": template["azimuth"]
                }).set_placement((cx, cy))
                
    doc.saveas(output_file)

    num_sectors_available = len(successful_sectors)
    proposal_summary = "Summary generation failed or image not provided."
    
    if image_path:
        llm_prompt = f"""
        You are an expert telecom structural and RF engineer analyzing a plan-view sketch of a tower headframe.
        
        Our automated geometry analysis has evaluated the physical spacing and 120° radiation crossfire clearances.
        
        RESULTS:
        - Total sectors evaluated: {len(sectors)}
        - Sectors capable of adding an extra antenna: {num_sectors_available} ({', '.join(successful_sectors)})
        
        Task:
        Write a concise, professional engineering summary for the deployment proposal. 
        Acknowledge the visual layout shown in the image (existing antennas vs the green proposed additions with their yellow radiation cones). 
        Mention that physical 500mm clearances and RF line-of-sight safety profiles have been verified. Keep the tone executive and ready for a technical report.
        """
        try:
            gemini_response = await call_llm(llm_prompt, image_paths=[image_path])
            # Handle standard structured or raw text responses safely
            if isinstance(gemini_response, dict):
                proposal_summary = gemini_response["candidates"][0]["content"]["parts"][0]["text"].strip()
            else:
                proposal_summary = str(gemini_response).strip()
        except Exception as e:
            proposal_summary = f"Error generating LLM summary: {str(e)}"

    return {
        "dxf_path": output_file,
        "available_sectors_count": num_sectors_available,
        "viable_sectors": successful_sectors,
        "proposal_summary": proposal_summary
    }


async def auto_analyse_ext_space(
    img: str = Form(None, description="The technical drawing image file")
    ):
    
    try:
   

        mcp_data = await run_pipeline(img)

        # mcp_data = {"calibration":{"pixel_to_mm_factor":8.4667,"assumed_dpi":300,"drawing_scale":"1:100","image_size_px":[536,522]},"headframe":{"shape":"pentagon","vertices":[[313,120],[378,111],[455,215],[310,308],[126,218]],"nodes":{"NODE_A":[370,113],"NODE_B":[430,218],"NODE_C":[280,302],"NODE_D":[150,218]}},"poles":[{"id":"pole_C1A1","from_node":"NODE_A","root_px":[370,113],"tip_px":[377.1,81.2],"azimuth":60.0,"equipment_id":"C1A1"},{"id":"pole_HEuA1","from_node":"NODE_A","root_px":[370,113],"tip_px":[389.1,102.0],"azimuth":60.0,"equipment_id":"HEuA1"},{"id":"pole_HEeA1","from_node":"NODE_A","root_px":[370,113],"tip_px":[401.1,122.8],"azimuth":60.0,"equipment_id":"HEeA1"},{"id":"pole_H3G_EE","from_node":"NODE_B","root_px":[430,218],"tip_px":[445.7,209.3],"azimuth":61.0,"equipment_id":"H3G_EE"},{"id":"pole_C2A1","from_node":"NODE_C","root_px":[280,302],"tip_px":[304.0,324.0],"azimuth":180.0,"equipment_id":"C2A1"},{"id":"pole_HEuB1","from_node":"NODE_C","root_px":[280,302],"tip_px":[280.0,324.0],"azimuth":180.0,"equipment_id":"HEuB1"},{"id":"pole_HEeB1","from_node":"NODE_C","root_px":[280,302],"tip_px":[256.0,324.0],"azimuth":180.0,"equipment_id":"HEeB1"},{"id":"pole_C3A1","from_node":"NODE_D","root_px":[150,218],"tip_px":[118.9,227.8],"azimuth":300.0,"equipment_id":"C3A1"},{"id":"pole_HEuC1","from_node":"NODE_D","root_px":[150,218],"tip_px":[130.9,207.0],"azimuth":300.0,"equipment_id":"HEuC1"},{"id":"pole_HEeC1","from_node":"NODE_D","root_px":[150,218],"tip_px":[142.9,186.2],"azimuth":300.0,"equipment_id":"HEeC1"}],"occupancy_map":[{"id":"C1A1","type":"Antenna","label":"C1A1","sector":"A","azimuth":60.0,"mount_node":"NODE_A","pole_tip_px":[377.1,81.2],"vertices":[[371.6,71.7],[382.6,90.7],[412.9,73.2],[401.9,54.2]],"width_px":22,"depth_px":35},{"id":"HEuA1","type":"Antenna","label":"HEuA1","sector":"A","azimuth":60.0,"mount_node":"NODE_A","pole_tip_px":[389.1,102.0],"vertices":[[383.6,92.5],[394.6,111.5],[424.9,94.0],[413.9,75.0]],"width_px":22,"depth_px":35},{"id":"HEeA1","type":"Antenna","label":"HEeA1","sector":"A","azimuth":60.0,"mount_node":"NODE_A","pole_tip_px":[401.1,122.8],"vertices":[[395.6,113.3],[406.6,132.3],[436.9,114.8],[425.9,95.8]],"width_px":22,"depth_px":35},{"id":"H3G_EE","type":"Dish","label":"H3G_EE","azimuth":61.0,"mount_node":"NODE_B","pole_tip_px":[445.7,209.3],"vertices":[[439.6,198.4],[451.8,220.2],[473.6,208.1],[461.5,186.2]],"width_px":25,"depth_px":25},{"id":"C2A1","type":"Antenna","label":"C2A1","sector":"B","azimuth":180.0,"mount_node":"NODE_C","pole_tip_px":[304.0,324.0],"vertices":[[315.0,324.0],[293.0,324.0],[293.0,359.0],[315.0,359.0]],"width_px":22,"depth_px":35},{"id":"HEuB1","type":"Antenna","label":"HEuB1","sector":"B","azimuth":180.0,"mount_node":"NODE_C","pole_tip_px":[280.0,324.0],"vertices":[[291.0,324.0],[269.0,324.0],[269.0,359.0],[291.0,359.0]],"width_px":22,"depth_px":35},{"id":"HEeB1","type":"Antenna","label":"HEeB1","sector":"B","azimuth":180.0,"mount_node":"NODE_C","pole_tip_px":[256.0,324.0],"vertices":[[267.0,324.0],[245.0,324.0],[245.0,359.0],[267.0,359.0]],"width_px":22,"depth_px":35},{"id":"C3A1","type":"Antenna","label":"C3A1","sector":"C","azimuth":300.0,"mount_node":"NODE_D","pole_tip_px":[118.9,227.8],"vertices":[[113.4,237.3],[124.4,218.3],[94.1,200.8],[83.1,219.8]],"width_px":22,"depth_px":35},{"id":"HEuC1","type":"Antenna","label":"HEuC1","sector":"C","azimuth":300.0,"mount_node":"NODE_D","pole_tip_px":[130.9,207.0],"vertices":[[125.4,216.5],[136.4,197.5],[106.1,180.0],[95.1,199.0]],"width_px":22,"depth_px":35},{"id":"HEeC1","type":"Antenna","label":"HEeC1","sector":"C","azimuth":300.0,"mount_node":"NODE_D","pole_tip_px":[142.9,186.2],"vertices":[[137.4,195.7],[148.4,176.7],[118.1,159.2],[107.1,178.2]],"width_px":22,"depth_px":35}]}
         
        mcp_data_up = scale_mcp_data_in_place(mcp_data)

        # generate_dxf_from_json(mcp_data, filename="cropped_temp_analysis_page_7.dxf")
        # dxf_path = process_site_analysis(mcp_data, output_file="cropped_temp_analysis_page_5.dxf")
        
        return mcp_data
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))