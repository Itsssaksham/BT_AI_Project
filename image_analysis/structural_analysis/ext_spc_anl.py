from analyse_pdf_tpvskt import analyse_pdf_tpvskt
from analyse_struc_space import analyse_struc_space
from mcp_ser import auto_analyse_ext_space

async def ext_spc_anl(
    pdf_file:str = Form(None, description="The technical drawing PDF"),
    antenna_details: str = Form(None, description="Antenna details in text format (Model, Height, etc.)")
    height: int = Form(None, description="Height of the antenna in meters")
):

    try:
        tpv_result = await analyse_pdf_tpvskt(antenna_details, pdf_file)
        
        img_crop_result = await analyse_struc_space(tpv_result["top_view_page"], height ,pdf_file)

        mcp_result = await auto_analyse_ext_space(img_crop_result["cropped_image_path"])

        return {
            "tpv_result": tpv_result,
            "img_crop_result": img_crop_result,
            "mcp_result": mcp_result
        }
        
    except Exception as e:
        logger.exception(f"Error during external space analysis: {str(e)}")
        return {"error": f"Error during external space analysis: {str(e)}"}
