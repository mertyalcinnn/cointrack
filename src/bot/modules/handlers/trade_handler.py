"""
Telegram botu için alım-satım işlemlerini yöneten modül
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Union, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import time
import re

from src.data_collectors.binance_trader import BinanceTrader
from src.bot.modules.utils.logger import setup_logger


class TradeHandler:
    """Alım-satım komutlarını yöneten sınıf"""

    def __init__(self, logger=None):
        """Trade handler sınıfını başlat"""
        self.logger = logger or setup_logger("TradeHandler")
        self.trader = BinanceTrader()
        self.logger.info("Trade Handler başlatıldı")

        # Kullanıcı onay durumlarını saklamak için
        self.pending_trades = (
            {}
        )  # {chat_id: {"action": "buy", "symbol": "BTC/USDT", "amount": 100}}

    async def handle_buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Alım komutunu işle"""
        try:
            chat_id = update.effective_chat.id

            # Argümanları kontrol et
            if not context.args or len(context.args) < 2:
                await update.message.reply_text(
                    "❌ Lütfen sembol ve miktarı belirtin!\n" "Örnek: /buy BTCUSDT 100"
                )
                return

            # Sembol ve miktarı al
            symbol = context.args[0].upper()
            amount = float(context.args[1])

            # USDT ekle
            if not "/USDT" in symbol:
                if "USDT" in symbol:
                    symbol = symbol.replace("USDT", "/USDT")
                else:
                    symbol = f"{symbol}/USDT"

            # Miktar kontrolü
            if amount <= 0:
                await update.message.reply_text("❌ Miktar pozitif olmalıdır!")
                return

            # Onay iste
            self.pending_trades[chat_id] = {
                "action": "buy",
                "symbol": symbol,
                "amount": amount,
                "timestamp": datetime.now().timestamp(),
            }

            # Fiyatı al
            price = await self.trader.get_symbol_price(symbol)

            if price <= 0:
                await update.message.reply_text(f"❌ {symbol} için fiyat alınamadı!")
                return

            # Hesap bakiyesini kontrol et
            account = await self.trader.get_account_info()
            usdt_balance = account.get("free", {}).get("USDT", 0)

            confirmation_msg = (
                f"🔄 Alım İşlemi Onayı\n\n"
                f"🪙 Coin: {symbol}\n"
                f"💰 Miktar: {amount} USDT\n"
                f"💵 Mevcut Bakiye: {usdt_balance:.2f} USDT\n"
                f"📊 Güncel Fiyat: ${price:.4f}\n\n"
                f"Tahmini alım miktarı: {amount / price:.8f} {symbol.split('/')[0]}\n\n"
                f"Bu işlemi onaylıyor musunuz?"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Onayla", callback_data=f"trade_confirm_buy_{chat_id}"
                        ),
                        InlineKeyboardButton(
                            "❌ İptal", callback_data=f"trade_cancel_{chat_id}"
                        ),
                    ]
                ]
            )

            await update.message.reply_text(confirmation_msg, reply_markup=keyboard)

        except ValueError:
            await update.message.reply_text(
                "❌ Geçersiz miktar! Lütfen sayısal bir değer girin."
            )
        except Exception as e:
            self.logger.error(f"Alım komutu hatası: {str(e)}")
            await update.message.reply_text(
                f"❌ İşlem sırasında bir hata oluştu: {str(e)}"
            )

    async def handle_sell(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Satış komutunu işle"""
        try:
            chat_id = update.effective_chat.id

            # Argümanları kontrol et
            if not context.args:
                # Argüman yoksa bakiyeleri listele
                balances = await self.trader.get_coin_balances(min_value=1.0)

                if not balances:
                    await update.message.reply_text("📊 Bakiyenizde coin bulunamadı.")
                    return

                msg = "📊 Coin Bakiyeleriniz:\n\n"
                for coin, data in balances.items():
                    if coin == "USDT":
                        continue
                    msg += f"🪙 {coin}: {data['free']:.8f} (${data['value_usdt']:.2f})\n"

                msg += "\nSatmak için: /sell BTCUSDT 0.001"
                await update.message.reply_text(msg)
                return

            if len(context.args) < 2:
                await update.message.reply_text(
                    "❌ Lütfen sembol ve miktarı belirtin!\n"
                    "Örnek: /sell BTCUSDT 0.001"
                )
                return

            # Sembol ve miktarı al
            symbol = context.args[0].upper()
            amount = float(context.args[1])

            # USDT ekle
            if not "/USDT" in symbol:
                if "USDT" in symbol:
                    symbol = symbol.replace("USDT", "/USDT")
                else:
                    symbol = f"{symbol}/USDT"

            # Miktar kontrolü
            if amount <= 0:
                await update.message.reply_text("❌ Miktar pozitif olmalıdır!")
                return

            # Bakiyeyi kontrol et
            coin_symbol = symbol.split("/")[0]
            account = await self.trader.get_account_info()
            coin_balance = account.get("free", {}).get(coin_symbol, 0)

            if amount > coin_balance:
                await update.message.reply_text(
                    f"❌ Yetersiz bakiye!\n"
                    f"Mevcut bakiye: {coin_balance:.8f} {coin_symbol}\n"
                    f"Satmak istediğiniz: {amount:.8f} {coin_symbol}"
                )
                return

            # Fiyatı al
            price = await self.trader.get_symbol_price(symbol)

            if price <= 0:
                await update.message.reply_text(f"❌ {symbol} için fiyat alınamadı!")
                return

            # Onay iste
            self.pending_trades[chat_id] = {
                "action": "sell",
                "symbol": symbol,
                "amount": amount,
                "timestamp": datetime.now().timestamp(),
            }

            confirmation_msg = (
                f"🔄 Satış İşlemi Onayı\n\n"
                f"🪙 Coin: {symbol}\n"
                f"💰 Miktar: {amount} {coin_symbol}\n"
                f"📊 Güncel Fiyat: ${price:.4f}\n"
                f"💵 Tahmini Değer: ${amount * price:.2f} USDT\n\n"
                f"Bu işlemi onaylıyor musunuz?"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Onayla", callback_data=f"trade_confirm_sell_{chat_id}"
                        ),
                        InlineKeyboardButton(
                            "❌ İptal", callback_data=f"trade_cancel_{chat_id}"
                        ),
                    ]
                ]
            )

            await update.message.reply_text(confirmation_msg, reply_markup=keyboard)

        except ValueError:
            await update.message.reply_text(
                "❌ Geçersiz miktar! Lütfen sayısal bir değer girin."
            )
        except Exception as e:
            self.logger.error(f"Satış komutu hatası: {str(e)}")
            await update.message.reply_text(
                f"❌ İşlem sırasında bir hata oluştu: {str(e)}"
            )

    async def handle_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bakiye komutunu işle"""
        try:
            chat_id = update.effective_chat.id

            # Bilgi mesajı
            await update.message.reply_text("📊 Bakiye bilgileri alınıyor...")

            # Bakiyeleri al (minimum 0.1 USDT değerinde olanları)
            balances = await self.trader.get_coin_balances(min_value=0.1)

            if not balances:
                await update.message.reply_text("📊 Bakiyenizde coin bulunamadı.")
                return

            # USDT bakiyesini ayrı göster
            usdt_balance = balances.get("USDT", {}).get("free", 0)

            msg = f"💵 USDT Bakiyeniz: ${usdt_balance:.2f}\n\n"
            msg += "📊 Diğer Coin Bakiyeleriniz:\n\n"

            for coin, data in balances.items():
                if coin == "USDT":
                    continue
                msg += f"🪙 {coin}: {data['free']:.8f} (${data['value_usdt']:.2f})\n"

            # Toplam değeri hesapla
            total_value = sum(data["value_usdt"] for data in balances.values())

            msg += f"\n💰 Toplam Portföy Değeri: ${total_value:.2f}"

            await update.message.reply_text(msg)

        except Exception as e:
            self.logger.error(f"Bakiye komutu hatası: {str(e)}")
            await update.message.reply_text(
                f"❌ Bakiye bilgileri alınırken bir hata oluştu: {str(e)}"
            )

    async def handle_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Emirleri listele"""
        try:
            chat_id = update.effective_chat.id

            # Bilgi mesajı
            await update.message.reply_text("📋 Açık emirler alınıyor...")

            # Açık emirleri al
            open_orders = await self.trader.get_open_orders()

            if not open_orders:
                await update.message.reply_text("📋 Açık emiriniz bulunmuyor.")
                return

            msg = "📋 Açık Emirleriniz:\n\n"

            for order in open_orders:
                symbol = order["symbol"]
                side = "ALIM 📈" if order["side"] == "buy" else "SATIŞ 📉"
                price = order["price"]
                amount = order["amount"]
                value = price * amount

                msg += f"🪙 {symbol} - {side}\n"
                msg += f"💰 Miktar: {amount:.8f}\n"
                msg += f"💵 Fiyat: ${price:.4f}\n"
                msg += f"💵 Değer: ${value:.2f}\n"
                msg += (
                    f"⏱️ Tarih: {datetime.fromtimestamp(order['timestamp']/1000)}\n\n"
                )

            msg += "Bir emri iptal etmek için: /cancel <emir_id>"

            await update.message.reply_text(msg)

        except Exception as e:
            self.logger.error(f"Emirler komutu hatası: {str(e)}")
            await update.message.reply_text(
                f"❌ Emirler alınırken bir hata oluştu: {str(e)}"
            )

    async def handle_cancel_order(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Emir iptal komutunu işle"""
        try:
            chat_id = update.effective_chat.id

            # Argümanları kontrol et
            if not context.args:
                await update.message.reply_text(
                    "❌ Lütfen iptal edilecek emir ID'sini belirtin!\n"
                    "Örnek: /cancel 12345678"
                )
                return

            order_id = context.args[0]

            # Açık emirleri al
            open_orders = await self.trader.get_open_orders()

            # Emir ID'sini kontrol et
            found_order = None
            for order in open_orders:
                if str(order["id"]) == order_id:
                    found_order = order
                    break

            if not found_order:
                await update.message.reply_text(f"❌ {order_id} ID'li emir bulunamadı!")
                return

            # Emir onayı
            symbol = found_order["symbol"]
            side = "ALIM 📈" if found_order["side"] == "buy" else "SATIŞ 📉"

            confirmation_msg = (
                f"🔄 Emir İptal Onayı\n\n"
                f"🪙 {symbol} - {side}\n"
                f"💰 Miktar: {found_order['amount']:.8f}\n"
                f"💵 Fiyat: ${found_order['price']:.4f}\n\n"
                f"Bu emri iptal etmek istediğinizden emin misiniz?"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Onayla",
                            callback_data=f"cancel_confirm_{order_id}_{symbol}",
                        ),
                        InlineKeyboardButton("❌ İptal", callback_data=f"cancel_reject"),
                    ]
                ]
            )

            await update.message.reply_text(confirmation_msg, reply_markup=keyboard)

        except Exception as e:
            self.logger.error(f"Emir iptal komutu hatası: {str(e)}")
            await update.message.reply_text(
                f"❌ İşlem sırasında bir hata oluştu: {str(e)}"
            )

    async def callback_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Callback query işleyici"""
        query = update.callback_query
        data = query.data
        chat_id = query.message.chat_id

        try:
            # Alım onayı
            if data.startswith("trade_confirm_buy_"):
                user_id = int(data.split("_")[-1])

                if user_id != chat_id:
                    await query.answer("Bu işlem sizin için değil!")
                    return

                if chat_id not in self.pending_trades:
                    await query.answer("İşlem zaman aşımına uğradı!")
                    await query.edit_message_text(
                        "❌ İşlem zaman aşımına uğradı. Lütfen tekrar deneyin."
                    )
                    return

                trade_info = self.pending_trades[chat_id]

                # Zaman aşımı kontrolü (5 dakika)
                if time.time() - trade_info["timestamp"] > 300:
                    await query.answer("İşlem zaman aşımına uğradı!")
                    await query.edit_message_text(
                        "❌ İşlem zaman aşımına uğradı. Lütfen tekrar deneyin."
                    )
                    del self.pending_trades[chat_id]
                    return

                # İşlemi gerçekleştir
                await query.answer("İşlem gerçekleştiriliyor...")

                result = await self.trader.buy_market(
                    symbol=trade_info["symbol"], amount=trade_info["amount"]
                )

                if result.get("success", False):
                    # Başarılı işlem
                    msg = (
                        f"✅ Alım işlemi başarılı!\n\n"
                        f"🪙 {result['symbol']}\n"
                        f"💰 Miktar: {result['amount']:.8f} {result['symbol'].split('/')[0]}\n"
                        f"💵 Değer: ${result['value']:.2f}\n"
                        f"📊 Fiyat: ${result['price']:.4f}\n"
                        f"⏱️ Tarih: {datetime.fromtimestamp(result['timestamp']/1000)}"
                    )
                    await query.edit_message_text(msg)
                else:
                    # Başarısız işlem
                    await query.edit_message_text(
                        f"❌ Alım işlemi başarısız!\n"
                        f"Hata: {result.get('error', 'Bilinmeyen hata')}"
                    )

                # İşlem bilgisini temizle
                del self.pending_trades[chat_id]

            # Satış onayı
            elif data.startswith("trade_confirm_sell_"):
                user_id = int(data.split("_")[-1])

                if user_id != chat_id:
                    await query.answer("Bu işlem sizin için değil!")
                    return

                if chat_id not in self.pending_trades:
                    await query.answer("İşlem zaman aşımına uğradı!")
                    await query.edit_message_text(
                        "❌ İşlem zaman aşımına uğradı. Lütfen tekrar deneyin."
                    )
                    return

                trade_info = self.pending_trades[chat_id]

                # Zaman aşımı kontrolü (5 dakika)
                if time.time() - trade_info["timestamp"] > 300:
                    await query.answer("İşlem zaman aşımına uğradı!")
                    await query.edit_message_text(
                        "❌ İşlem zaman aşımına uğradı. Lütfen tekrar deneyin."
                    )
                    del self.pending_trades[chat_id]
                    return

                # İşlemi gerçekleştir
                await query.answer("İşlem gerçekleştiriliyor...")

                result = await self.trader.sell_market(
                    symbol=trade_info["symbol"], amount=trade_info["amount"]
                )

                if result.get("success", False):
                    # Başarılı işlem
                    msg = (
                        f"✅ Satış işlemi başarılı!\n\n"
                        f"🪙 {result['symbol']}\n"
                        f"💰 Miktar: {result['amount']:.8f} {result['symbol'].split('/')[0]}\n"
                        f"💵 Değer: ${result['value']:.2f}\n"
                        f"📊 Fiyat: ${result['price']:.4f}\n"
                        f"⏱️ Tarih: {datetime.fromtimestamp(result['timestamp']/1000)}"
                    )
                    await query.edit_message_text(msg)
                else:
                    # Başarısız işlem
                    await query.edit_message_text(
                        f"❌ Satış işlemi başarısız!\n"
                        f"Hata: {result.get('error', 'Bilinmeyen hata')}"
                    )

                # İşlem bilgisini temizle
                del self.pending_trades[chat_id]

            # İşlem iptali
            elif data.startswith("trade_cancel_"):
                user_id = int(data.split("_")[-1])

                if user_id != chat_id:
                    await query.answer("Bu işlem sizin için değil!")
                    return

                if chat_id in self.pending_trades:
                    del self.pending_trades[chat_id]

                await query.answer("İşlem iptal edildi!")
                await query.edit_message_text("❌ İşlem iptal edildi.")

            # Emir iptal onayı
            elif data.startswith("cancel_confirm_"):
                parts = data.split("_")
                order_id = parts[2]
                symbol = parts[3]

                await query.answer("Emir iptal ediliyor...")

                result = await self.trader.cancel_order(symbol, order_id)

                if result.get("success", False):
                    await query.edit_message_text(
                        f"✅ Emir başarıyla iptal edildi!\n" f"Emir ID: {order_id}"
                    )
                else:
                    await query.edit_message_text(
                        f"❌ Emir iptal edilemedi!\n"
                        f"Hata: {result.get('error', 'Bilinmeyen hata')}"
                    )

            # Emir iptal reddi
            elif data == "cancel_reject":
                await query.answer("İptal edildi!")
                await query.edit_message_text("✅ Emir iptal etme işlemi iptal edildi.")

        except Exception as e:
            self.logger.error(f"Callback handler hatası: {str(e)}")
            await query.answer("Bir hata oluştu!")
            try:
                await query.edit_message_text(
                    f"❌ İşlem sırasında bir hata oluştu: {str(e)}"
                )
            except:
                pass

    # Telegram botu için handler'ları kaydet
    def register_handlers(self, application):
        """Handler'ları kaydet"""
        application.add_handler(CommandHandler("buy", self.handle_buy))
        application.add_handler(CommandHandler("sell", self.handle_sell))
        application.add_handler(CommandHandler("balance", self.handle_balance))
        application.add_handler(CommandHandler("orders", self.handle_orders))
        application.add_handler(CommandHandler("cancel", self.handle_cancel_order))
        application.add_handler(CallbackQueryHandler(self.callback_handler, pattern="^(trade_|cancel_)"))
