import os
import requests

def setup_assets():
    """Gerekli asset dosyalarını hazırla"""
    assets_dir = 'src/assets'
    if not os.path.exists(assets_dir):
        os.makedirs(assets_dir)
    
    # Örnek uyarı sesi
    alert_file = f'{assets_dir}/alert.mp3'
    if not os.path.exists(alert_file):
        # Örnek bir uyarı sesi URL'si (kendi sesinizi kullanabilirsiniz)
        alert_url = "https://example.com/alert.mp3"
        response = requests.get(alert_url)
        with open(alert_file, 'wb') as f:
            f.write(response.content)

if __name__ == '__main__':
    setup_assets() 