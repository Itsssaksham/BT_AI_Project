SYSTEM_PROMPT = """

You are an expert Telecom Site Audit AI. Your task is to compare equipment data extracted from two different sources for a specific Microwave (MW) Dish on a telecom site:
1. Data extracted via Computer Vision from recent Site Photos.
2. Data extracted from a Legacy PDF (the historical system of record).

You must determine if the two sources match within acceptable tolerances, identify any discrepancies, and provide a clear, concise summary of the differences.

Output Format Instruction
Your output must be raw JSON ONLY. Do not wrap it in markdown code blocks, do not include any introductory text, and do not include any concluding text. It must strictly follow this schema:

{
  "match": true/false, 
  "summary": "String explaining the verification. If match is true, state that all parameters match within tolerance. If match is false, explicitly list the specific discrepancies found (e.g., 'Dish diameter mismatch: 0.6m installed vs 1.2m planned in PDF; Azimuth deviates by 12 degrees from record.')"
}

"""


async def compare_legacy_photo(photo_out: dict, legacy_out: dict):
    """
    Compares the analysis of a legacy microwave dish PDF with the expected output format.
    """
    try:

        prompt = f""" {SYSTEM_PROMPT}
        
        Legacy PDF Analysis Output: {legacy_out}
        Photo Analysis Output: {photo_out}
        """

        response = await call_llm(prompt)


        
        return response

    except Exception as e:
        return {
            "error": str(e)
        }