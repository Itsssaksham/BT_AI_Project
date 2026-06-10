from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import base64
import requests
import json
from typing import Optional, Dict, Any
import re
import os

def extract_json(text: str):
    # remove markdown ```json ``` wrappers if present
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError("No JSON found")

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
VISION_MODEL = "qwen3-vl:30b-a3b"  # Change to "llama3.2:3b-vision-instruct" if preferred

# Your fixed system prompt (very long ? kept as-is)
SYSTEM_PROMPT = """
Objective: Analyze the provided image to determine if it depicts a telecom "transmission rack."

Output Format:
BOOLEAN: True if it is a transmission rack, False otherwise.
REASONING: A brief explanation (1-3 sentences) supporting the boolean decision, referencing specific visual cues.

Analysis Guidelines:
Identify a "transmission rack" by looking for the presence of at least two strong indicators from Section A, and the absence of dominant features from Section C. The presence of any strong indicator from Section A heavily weighs towards "True."
Section A: Strong Positive Indicators (Core Transmission Components)
Fiber Optic Cabling:
High density of yellow fiber optic patch cables. These are typically thinner than copper cables and often have distinct LC, SC, or FC connectors.
Visible fiber optic management elements: Fiber management trays, spools, or loops designed to protect and organize fiber cables.
Optical Distribution Frames (ODF) or Fiber Optic Patch Panels: Rack-mounted units with numerous small ports specifically for fiber connections.
Optical Transport Equipment:
Specific Brand/Model Recognition: Look for labels such as "ADVA FSP [e.g., 3000]," "Cisco [Carrier-grade router/switch models with many fiber ports]," "Nokia / Alcatel-Lucent [Optical Network Units]," or "Huawei [Optical Transport Network (OTN) equipment]."
Wavelength Division Multiplexing (WDM/DWDM/CWDM) equipment: Chassis and cards designed for combining multiple optical signals.
DC Power Infrastructure (Indicative for Telecom):
Visible -48V DC Power Distribution Units (PDUs): Labels explicitly stating "-48V DC" or showing terminal blocks for high-current DC feeds.
Heavy gauge DC power cables: Often thicker red and black cables indicating primary DC power delivery.
Section B: Supporting Positive Indicators (Common in Transmission Racks)
Alarm Systems:
Dedicated Alarm Modules/Serializers: Equipment labeled "ALARM SERIALISER," "HUAWEI ALARMS," or similar, designed to aggregate equipment alarms.
Bundles of thin alarm wires: Often multi-core cables connecting to alarm inputs.
Specific Rack-Mounted Units:
Modular Chassis Systems: Equipment composed of multiple slot-in cards within a main frame, common for optical line cards, cross-connects, etc.
High-density network interfaces: Units with a large number of communication ports (especially optical).
Section C: Negative Indicators (Less Likely to be a Pure Transmission Rack)
Dominant RF Coaxial Cabling: A high density of thick, rigid coaxial cables (e.g., for microwave radios, cellular base stations, antennas).
Generic Computing Hardware: Presence of standard desktop PCs, enterprise servers, or storage arrays not typically found in core transmission infrastructure.
Large Rectifier Banks: While essential for DC power, primary large-scale rectifier units are often in separate power cabinets, not typically within a transmission rack itself. Smaller PDUs are common inside transmission racks.
Example Output (Illustrative):

Scenario 1 (Strong Match):
BOOLEAN: True
REASONING: The image clearly shows an ADVA FSP 3000 unit, numerous yellow fiber optic patch cables, and a -48V DC power distribution unit.
Scenario 2 (Weak Match / Unclear):
BOOLEAN: False
REASONING: The image predominantly displays thick coaxial cables and what appears to be RF amplifier units, with no clear optical transport equipment or significant fiber optic cabling.
Scenario 3 (Mixed but leaning Transmission):
BOOLEAN: True
REASONING: Although some copper cabling is present, the rack features an optical distribution frame, multiple fiber splice enclosures, and equipment labeled for optical line termination.
"""

def encode_image(file: UploadFile) -> str:
    """Encode uploaded file to base64"""
    content = file.file.read()
    return base64.b64encode(content).decode("utf-8")

async def analyse_txrack(
    target_image: UploadFile = File(..., description="Target site survey photo to check")
):
    try:
        
        base64_target = encode_image(target_image)

        # Use provided prompt or default
        system_content = SYSTEM_PROMPT

        payload = {
            "model": VISION_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": system_content
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Image 1 (Target) is attached."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_target}"}}
                    ]
                }
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
            "stream": False
        }

        response = requests.post(OLLAMA_URL, json=payload, timeout=1200)

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Ollama error: {response.text}")

        data = response.json()
        raw_content = data["choices"][0]["message"]["content"]

        try:
            result = extract_json(raw_content)
        except Exception:
            result = {"error": "Model did not return valid JSON", "raw": raw_content}

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

"""
Objective: Analyze the provided image to determine whether it depicts a telecom "transmission rack."

---

### Output Format (STRICT)

BOOLEAN: True or False
CONFIDENCE: High / Medium / Low
REASONING: 1–3 concise sentences referencing ONLY clearly visible elements in the image.

---

### Step-by-Step Analysis (MANDATORY)

Step 1: Identify Visible Components
List the clearly visible components in the image (e.g., fiber cables, terminal blocks, branded equipment, power units, alarm modules).
→ Do NOT assume or infer anything that is not clearly visible.

Step 2: Categorize Components
Classify each identified component into one of:

* Fiber / Optical
* Power (DC/AC)
* Alarm / Control
* Copper / RF
* Unknown

Step 3: Scoring Logic
Assign scores based ONLY on visible evidence:

+2 → Strong Optical Indicator

* High density of yellow fiber optic cables
* Optical Distribution Frame (ODF) / fiber patch panel
* Clearly identifiable optical transport equipment (e.g., ADVA, Huawei OTN, Nokia optical systems)

+1 → Supporting Indicator

* Alarm modules / alarm wiring
* Modular telecom chassis systems
* High-density communication ports

-2 → Strong Negative Indicator

* Dominant thick RF coaxial cabling
* Generic IT hardware (servers, CPUs, storage systems)
* Large standalone rectifier units dominating the rack

Step 4: Decision Rule

* If total score ≥ 2 → BOOLEAN = True
* If total score < 2 → BOOLEAN = False

Important Rules:

* At least ONE strong optical indicator (+2) is required for True
* Supporting indicators alone are NOT sufficient
* If evidence is unclear or insufficient → return False

---

### Additional Constraints

* Only consider clearly visible elements; do NOT infer hidden components
* Do NOT guess based on context or typical telecom setups
* Prefer False over uncertain True
* Avoid over-reasoning or assumptions

---

### Output Example

BOOLEAN: True
CONFIDENCE: High
REASONING: The rack contains identifiable ADVA optical equipment and multiple fiber-related modules, indicating a transmission setup.

BOOLEAN: False
CONFIDENCE: Medium
REASONING: The image shows terminal blocks and mixed cabling but lacks clear optical transport equipment or dense fiber infrastructure.

"""