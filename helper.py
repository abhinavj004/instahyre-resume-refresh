import base64

def get_resume_payload(
    pdf_path,
    candidate_id,
    resume_id,
    filename
):
    with open(pdf_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {
        "calculate_opps": True,
        "candidate":
            f"/api/v1/candidate_misc/profile/limited_candidate/{candidate_id}",
        "resource_uri":
            f"/api/v1/candidate_misc/profile/resume/{resume_id}",
        "title": filename,
        "file_b64":
            f"data:application/pdf;base64,{encoded}"
    }