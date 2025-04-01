"""
Telegram bot için import modülü
"""

# Mevcut imports buraya eklenebilir
from src.bot.ai_analysis_command import cmd_aianalysis

# Metodu TelegramBot sınıfına ata
def register_ai_command(TelegramBot):
    # Monkey patch - cmd_aianalysis metodunu TelegramBot sınıfına ekle
    TelegramBot.cmd_aianalysis = cmd_aianalysis

# Tüm metodları kaydet
def register_all_commands(bot_instance):
    register_ai_command(bot_instance.__class__)
