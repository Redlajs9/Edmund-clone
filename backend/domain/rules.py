KEYMAP = {
    "IO": ["ventil", "ventily", "pump", "pumpa", "čidlo", "snímač", "kanál", "adresa"],
    "CIP_SEQ": ["cip", "seq", "dávka", "recept", "krok", "ocm"],
    "ALARM": ["alarm", "porucha", "chyba", "fault", "code"],
    "NET": ["profinet", "profibus", "opc", "ua", "síť", "ip", "endpoint"],
    "DIAG": ["diagnostika", "běžící", "trend", "historie"],
}

NEEDS = {
    "IO": ["PLC tag list (I/O list)", "PLC HW config", "Units & scaling"],
    "CIP_SEQ": ["ProLeiT DB schema", "SEQ/OCM export", "P&ID", "Tag mapping PLC↔DB"],
    "ALARM": ["Alarm matrix", "ProLeiT alarms/events", "Tag mapping"],
    "NET": ["Síťová topologie", "OPC UA endpoints + certs"],
    "DIAG": ["Historizační DB", "Live OPC/SQL přístup", "Tag mapping"],
}

WHY = {
    "PLC tag list (I/O list)": "Vazba fyzických I/O na technologické objekty.",
    "PLC HW config": "Adresace a typy modulů.",
    "Units & scaling": "Správná interpretace hodnot (°C, l/h, %).",
    "ProLeiT DB schema": "Čtení SEQ/OCM a stavů výroby.",
    "SEQ/OCM export": "Mapování kroků/sekvencí na objekty a signály.",
    "P&ID": "Technologické vazby a toky médií.",
    "Tag mapping PLC↔DB": "Spojení názvů v DB s tagy v PLC.",
    "Alarm matrix": "Kódy, závažnost, podmínky.",
    "ProLeiT alarms/events": "Historie a živé události.",
    "Síťová topologie": "Kde běží endpointy a jak se připojit.",
    "OPC UA endpoints + certs": "Bezpečný přístup ke live datům.",
    "Historizační DB": "Trendy a zpětná diagnostika.",
    "Live OPC/SQL přístup": "Dotazy na aktuální hodnoty/stavy.",
}

def analyze_missing(q: str):
    ql = q.lower()
    hit_keys = [k for k, words in KEYMAP.items() if any(w in ql for w in words)]
    missing = []
    for k in hit_keys:
        missing += NEEDS[k]
    # deduplikace, zachová pořadí
    missing = list(dict.fromkeys(missing))
    return missing, WHY
