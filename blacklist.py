"""
Kara liste yapılandırması - TL, EURO gibi fiat para birimlerini ve diğer hariç tutulacak coinleri tanımlar.
"""

# Kara listeye alınacak sembol kalıpları
BLACKLIST_PATTERNS = [
    'EUR', 'TRY', 'GBP', 'AUD', 'RUB', 'JPY', 'CAD',  # Fiat para birimleri
    'UP/', 'DOWN/', 'BULL/', 'BEAR/',  # Kaldıraçlı tokenlar
    'BUSD/', 'TUSD/', 'DAI/', 'USDC/', 'USDD/',  # Stablecoin çiftleri
    'BIDR', 'BKRW', 'IDRT', 'UAH', 'NGN', 'BVND'  # Diğer yerel para birimleri
]

def is_blacklisted(symbol: str) -> bool:
    """
    Verilen sembolün kara listede olup olmadığını kontrol eder.
    
    Args:
        symbol: Kontrol edilecek coin sembolü
        
    Returns:
        bool: Eğer sembol kara listede ise True, değilse False
    """
    return any(pattern in symbol for pattern in BLACKLIST_PATTERNS)
