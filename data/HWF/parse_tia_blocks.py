import os, csv, xml.etree.ElementTree as ET
from pathlib import Path

# Jaké typy bloků hledáme
TYPES = ("SW.Blocks.FB", "SW.Blocks.FC", "SW.Blocks.DB", "SW.Blocks.OB")

def localname(tag):
    # odstraní XML namespace: {ns}Name -> Name
    if "}" in tag: return tag.split("}",1)[1]
    return tag

def detect_block(xml_path):
    """Vrátí (typ, name) nebo None, pokud soubor není blok."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError:
        return None

    root_lname = localname(root.tag)
    if root_lname not in TYPES:
        return None

    # jméno bloku bývá v AttributeList/Name
    name_el = root.find(".//{*}AttributeList/{*}Name")
    name = name_el.text if name_el is not None else Path(xml_path).stem
    return (root_lname.replace("SW.Blocks.",""), name)

def folder_from_path(xml_path):
    """
    Vrátí relativní složku od 'Program blocks' (nebo ekvivalentu v češtině/němčině).
    Když ji nenajde, vrátí relativní cestu od rootu exportu.
    """
    parts = Path(xml_path).parts
    # najdi index „Program blocks“ (může být i „Programmbaugruppen“, „Programové bloky“ apod.)
    anchors = {"Program blocks", "Programmbaugruppen", "Programové bloky", "Programmi", "Program"}
    idx = None
    for i,p in enumerate(parts):
        if p in anchors:
            idx = i; break
    if idx is None:
        # fallback: vezmi nadřazené složky souboru
        return str(Path(*Path(xml_path).parent.parts))
    # složka mezi „Program blocks“ a adresářem bloku
    rel = Path(*parts[idx+1:-1])  # bez názvu souboru
    return str(rel) if str(rel) else "/"

def scan_export(root_dir):
    rows = []
    for dirpath, _, files in os.walk(root_dir):
        for f in files:
            if not f.lower().endswith(".xml"):
                continue
            xml_path = os.path.join(dirpath, f)
            dtype_name = detect_block(xml_path)
            if not dtype_name:
                continue
            btype, bname = dtype_name
            folder = folder_from_path(xml_path)
            rows.append((folder, btype, bname, os.path.relpath(xml_path, root_dir)))
    return sorted(rows)

if __name__ == "__main__":
    ROOT = "."  # nebo zadej absolutní cestu ke kořeni exportu
    rows = scan_export(ROOT)

    # výpis do konzole
    current = None
    for folder, btype, bname, rel in rows:
        if folder != current:
            print(f"\n[{folder}]")
            current = folder
        print(f"  - {btype}: {bname}")

    # zároveň uloží CSV mapu
    out = Path("tia_blocks_by_folder.csv")
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Folder","Type","BlockName","RelativeXML"])
        w.writerows(rows)
    print(f"\nUloženo: {out.resolve()}")
