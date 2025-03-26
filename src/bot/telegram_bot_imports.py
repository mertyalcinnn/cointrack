# Yeni çoklu zaman dilimi analizi için importlar
from src.analysis.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from src.bot.multi_timeframe_scan import scan_command_multi, send_multi_timeframe_results, _get_test_multi_opportunities

# Mevcut init metoduna eklenecek kod
def __init__(self, token: str):
    # ... (mevcut kod) ...
    
    # MultiTimeframeAnalyzer'ı başlat
    self.multi_analyzer = None  # Lazy initialization - ilk kullanımda başlatılacak
    
    # ... (mevcut kodun geri kalanı) ...

# register_handlers metoduna eklenecek kod
def register_handlers(self):
    # ... (mevcut kod) ...
    
    # Çoklu zaman dilimi tarama komutu
    self.application.add_handler(CommandHandler("multiscan", self.scan_command_multi))
    
    # ... (mevcut kodun geri kalanı) ...

# Yeni metodların ana sınıfa eklenmesi için
async def scan_command_multi(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await scan_command_multi(self, update, context)

async def send_multi_timeframe_results(self, chat_id, opportunities):
    return await send_multi_timeframe_results(self, chat_id, opportunities)

def _get_test_multi_opportunities(self):
    return _get_test_multi_opportunities(self)
