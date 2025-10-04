from fastapi import APIRouter

router = APIRouter()

@router.get("/readiness")
def readiness():
    # zatím natvrdo – později podle reálných datových zdrojů
    return {
        "pids": False,
        "electrical_drawings": False,
        "process_sequences": False,
        "proleit_db": False,
        "tia_exports": False,
        "opcua": False
    }
