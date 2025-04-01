"""
Bu kodu telegram_bot.py dosyanıza aşağıdaki şekilde entegre edin:

1. Import ekleyin:
from src.bot.multi_timeframe_handler import MultiTimeframeHandler

2. TelegramBot sınıfının __init__ metoduna aşağıdaki kodu ekleyin:
"""

# __init__ metoduna eklenecek:
self.multi_handler = MultiTimeframeHandler(logger=self.logger, bot_instance=self)

"""
3. register_handlers metoduna aşağıdaki kodu ekleyin:
"""

# register_handlers metoduna eklenecek:
await self.multi_handler.register_handlers(self.application)

"""
4. handle_callback_query metoduna yeni callback veri tipi ekleyin:
"""

# handle_callback_query metoduna eklenecek (uygun yere):
# Tarama yenileme butonu
elif callback_data == "refresh_multi":
    await self.multi_handler.refresh_multi_callback(update, context)

"""
5. Bot başlatma kod bloğuna eklenecek:
"""

# start metoduna eklenecek:
# MultiTimeframeHandler'ı başlat
await self.multi_handler.initialize()

"""
Böylece `/multiscan` komutu kullanılabilir hale gelecek ve çoklu zaman dilimi analizi yapabileceksiniz.
"""