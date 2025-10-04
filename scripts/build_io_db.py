# scripts/build_io_db.py
import csv, os, sqlite3, re

BASE = os.path.dirname(os.path.dirname(__file__))  # -> C:\Users\mr\Edmund-clone
SRC = os.path.join(BASE, "data", "IO-list", "PLC4_IOList.txt")
DB  = os.path.join(BASE, "data", "io.db")

os.makedirs(os.path.dirname(DB), exist_ok=True)
con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS io (
  tag      TEXT,
  desc1    TEXT,
  desc2    TEXT,
  extra    TEXT,
  io_type  TEXT,   -- 'E' = vstup, 'A' = výstup, EW/AW/ED/AD = slova/DW…
  address  TEXT,   -- např. '20.0' nebo '1056'
  datatype TEXT,
  comment  TEXT
);
""")
cur.execute("DELETE FROM io;")

with open(SRC, "r", encoding="utf-8", errors="ignore") as f:
    rdr = csv.reader(f, delimiter=';')
    for row in rdr:
        # zarovnání na 8 sloupců
        row += [""] * (8 - len(row))
        tag, desc1, desc2, extra, io_type, address, datatype, comment = row[:8]
        tag = tag.strip()
        io_type = io_type.strip()
        address = address.strip()
        if not tag and not io_type:
            continue
        cur.execute(
            "INSERT INTO io(tag,desc1,desc2,extra,io_type,address,datatype,comment) VALUES(?,?,?,?,?,?,?,?)",
            (tag,desc1,desc2,extra,io_type,address,datatype,comment)
        )

con.commit()
con.close()
print("✅ Imported into", DB)
